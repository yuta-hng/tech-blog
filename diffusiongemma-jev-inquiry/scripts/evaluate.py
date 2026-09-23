#!/usr/bin/env python3
"""Evaluate /v1/systemone with text-only inputs and original, unmodified labels.

Raw response JSONL is authoritative. No retry hides HTTP errors. A warmup is
recorded separately; client timings exclude token acquisition but include HTTP.
"""
import argparse
import concurrent.futures
import copy
import csv
import datetime
import hashlib
import http.client
import json
import math
import random
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen


def payload(questions, text, samples=1, steps=1):
    wire_questions = copy.deepcopy(questions)
    # The SDK calls this boolean, but the raw Jev endpoint requires noul.
    for q in wire_questions.values():
        if q['type'] == 'boolean':
            q['type'] = 'noul'
    return {'model': 'jev-latest', 'state': text, 'questions': wire_questions,
            'samples': samples, 'steps': steps, 'seed': 42}


def probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('invalid probability')
    return float(value)


def distribution(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('probability labels do not match expected labels')
    result = {k: probability(value[k]) for k in keys}
    if not math.isclose(sum(result.values()), 1, abs_tol=0.001):
        raise ValueError('probabilities do not sum to one')
    return result


def decode(body, departments):
    a = body['answers']
    dp = distribution(a['department']['probabilities'], departments)
    sp = distribution(a['severity']['probabilities'], ['0', '1', '2'])
    hp = probability(a['needsHuman']['noul'])
    dep = a['department']['choice']
    if dep not in dp or dp[dep] < max(dp.values()):
        raise ValueError('choice inconsistent with probability distribution')
    # The API score is an expectation, not the most likely class. Do not round it.
    sev = int(max(sp, key=sp.get))
    expected_score = sum(int(k) * v for k, v in sp.items())
    if not isinstance(a['severity']['score'], (int, float)) or not math.isclose(a['severity']['score'], expected_score, abs_tol=0.001):
        raise ValueError('score inconsistent with probabilities')
    return {
        'prediction': {'department': dep, 'severity': sev, 'needsHuman': hp >= 0.5},
        'confidence': {'department': dp[dep], 'severity': sp[str(sev)], 'needsHuman': max(hp, 1-hp)},
        'severity_expected_score': expected_score,
        'needsHuman_probability': hp,
        'ties': {'department': sum(v == max(dp.values()) for v in dp.values()) > 1,
                 'severity': sum(v == max(sp.values()) for v in sp.values()) > 1,
                 'needsHuman': hp == 0.5},
    }


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values)-1)*q
    low, high = math.floor(pos), math.ceil(pos)
    return values[low] + (values[high]-values[low])*(pos-low)


def summarize(records, total, duration, departments):
    ok = [r for r in records if r.get('valid')]
    result = {'attempted': total, 'valid_responses': len(ok), 'failed': total-len(ok),
              'wall_seconds': duration, 'successful_requests_per_second': len(ok)/duration if duration else None,
              'error_rate': (total-len(ok))/total, 'accuracy': {}, 'confusion': {}}
    for k, labels in [('department', departments), ('severity', [0, 1, 2]), ('needsHuman', [False, True])]:
        matrix = {str(g): {str(p): 0 for p in labels} for g in labels}
        for r in ok:
            matrix[str(r['gold'][k])][str(r['prediction'][k])] += 1
        correct = sum(r['gold'][k] == r['prediction'][k] for r in ok)
        result['accuracy'][k] = {'correct': correct, 'of_all_attempted': correct/total,
                                 'of_valid_responses': correct/len(ok) if ok else None}
        result['confusion'][k] = matrix
    result['all_three_correct'] = sum(r['gold'] == r['prediction'] for r in ok)
    result['all_three_accuracy_of_all_attempted'] = result['all_three_correct']/total
    result['human_required_missed'] = [r['id'] for r in ok if r['gold']['needsHuman'] and not r['prediction']['needsHuman']]
    result['urgent_missed'] = [r['id'] for r in ok if r['gold']['severity'] == 2 and r['prediction']['severity'] != 2]
    for k in ['human_required', 'urgent']:
        eligible = [r for r in records if r['gold']['needsHuman']] if k == 'human_required' else [r for r in records if r['gold']['severity'] == 2]
        field, positive = ('needsHuman', True) if k == 'human_required' else ('severity', 2)
        result[k+'_recall_including_failed'] = sum(r.get('valid', False) and r['prediction'][field] == positive for r in eligible)/len(eligible) if eligible else None
    result['severity_mae_valid'] = sum(abs(r['gold']['severity'] - r['severity_expected_score']) for r in ok)/len(ok) if ok else None
    for name, subset in [('all', ok), ('tricky', [r for r in ok if r['tricky']]), ('non_tricky', [r for r in ok if not r['tricky']])]:
        result[name+'_valid_summary'] = {'n': len(subset), 'all_three_correct': sum(r['gold'] == r['prediction'] for r in subset)}
    for metric in ['client_ms', 'server_ms']:
        values = [r[metric] for r in ok if isinstance(r.get(metric), (int, float))]
        result[metric] = {'n': len(values), 'p50': percentile(values, .5), 'p95': percentile(values, .95)}
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', required=True)
    p.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1]/'data/inquiry_testset.json')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--client-location', required=True, help='Actual runner location; never infer Japan from user locale')
    p.add_argument('--account', help='Optional gcloud account; defaults to the active account')
    p.add_argument('--auth', choices=['gcloud', 'metadata'], default='gcloud')
    p.add_argument('--samples', default='1', choices=['1', 'auto'])
    p.add_argument('--steps', type=int, default=1)
    p.add_argument('--concurrency', type=int, default=1)
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--no-warmup', action='store_true')
    args = p.parse_args()
    if args.concurrency < 1 or args.concurrency > 32 or args.repeats < 1:
        p.error('concurrency must be 1..32 and repeats must be >= 1')
    endpoint = urlsplit(args.url)
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        p.error('a clean HTTPS Cloud Run service URL is required')
    args.out.mkdir(parents=True, exist_ok=False)
    raw = args.dataset.read_bytes()
    data = json.loads(raw)
    deps = list(data['questions']['department']['criteria'])
    if args.auth == 'metadata':
        req = Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience='+quote(args.url, safe=''),
                      headers={'Metadata-Flavor': 'Google'})
        with urlopen(req, timeout=10) as response:
            token = response.read().decode().strip()
    else:
        token_command = ['gcloud', 'auth', 'print-identity-token']
        if args.account:
            token_command.append('--account='+args.account)
        token = subprocess.run(token_command,
                               text=True, check=True, stdout=subprocess.PIPE).stdout.strip()
    local = threading.local()
    samples = 'auto' if args.samples == 'auto' else 1
    manifest = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'dataset_sha256': hashlib.sha256(raw).hexdigest(),
                'url': args.url, 'client_location': args.client_location,
                'samples': samples, 'steps': args.steps, 'concurrency': args.concurrency,
                'repeats': args.repeats, 'seed': 42, 'shuffle_seed': 20260923,
                'input': 'state is inquiry text only; no id, labels, note, or tricky',
                'boolean_wire_type': 'noul', 'severity_class': 'argmax(probabilities), first level on tie',
                'boolean_rule': 'P(true) >= 0.5', 'retries': 0,
                'timing': 'token acquired before timing; HTTPS connection reused per worker when possible; warmup excluded',
                'server_timing': 'diagnostics.timing.total_ms, not Cloud Monitoring nor pure GPU time',
                'questions': data['questions']}
    (args.out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')

    def call(job):
        index, item = job
        body = json.dumps(payload(data['questions'], item['text'], samples, args.steps), ensure_ascii=False).encode()
        rec = {'index': index, 'id': item['id'], 'gold': item['labels'], 'tricky': item['tricky'],
               'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'valid': False}
        start = time.perf_counter()
        try:
            if not getattr(local, 'conn', None):
                local.conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port, timeout=args.timeout)
            local.conn.request('POST', endpoint.path.rstrip('/')+'/v1/systemone', body=body,
                               headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json; charset=utf-8'})
            response = local.conn.getresponse()
            response_body = response.read()
            rec['client_ms'] = (time.perf_counter()-start)*1000
            rec['status'] = response.status
            try:
                rec['raw_response'] = json.loads(response_body)
            except (ValueError, UnicodeDecodeError):
                rec['raw_response_text'] = response_body.decode(errors='replace')
                raise
            if response.status != 200:
                raise ValueError('HTTP '+str(response.status))
            rec.update(decode(rec['raw_response'], deps))
            rec['server_ms'] = rec['raw_response'].get('diagnostics', {}).get('timing', {}).get('total_ms')
            rec['valid'] = True
        except Exception as e:
            rec.setdefault('client_ms', (time.perf_counter()-start)*1000)
            rec['error'] = type(e).__name__+': '+str(e)
            if getattr(local, 'conn', None):
                local.conn.close()
                local.conn = None
        return rec

    if not args.no_warmup:
        warm = call((-1, data['items'][0]))
        (args.out/'warmup.json').write_text(json.dumps(warm, ensure_ascii=False, indent=2)+'\n')
        if not warm['valid']:
            raise SystemExit('Warmup failed. See warmup.json; bulk evaluation was not started.')
    items = data['items']*args.repeats
    random.Random(20260923).shuffle(items)
    results = []
    start = time.perf_counter()
    with (args.out/'responses.jsonl').open('w') as out, concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(call, job) for job in enumerate(items)]
        for future in concurrent.futures.as_completed(futures):
            rec = future.result()
            out.write(json.dumps(rec, ensure_ascii=False)+'\n')
            out.flush()
            results.append(rec)
            print(f"{len(results)}/{len(items)} {rec['id']} valid={rec['valid']} ms={rec['client_ms']:.1f}", flush=True)
    duration = time.perf_counter()-start
    summary = summarize(results, len(items), duration, deps)
    (args.out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    with (args.out/'predictions.csv').open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['id', 'valid', 'tricky', 'client_ms', 'server_ms', 'error'] + [f'{k}_{suffix}' for k in ['department', 'severity', 'needsHuman'] for suffix in ['gold', 'pred', 'confidence']]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in sorted(results, key=lambda x:x['index']):
            row = {k:r.get(k, '') for k in fields[:6]}
            for k in ['department', 'severity', 'needsHuman']:
                row.update({k+'_gold':r['gold'][k], k+'_pred':r.get('prediction', {}).get(k, ''), k+'_confidence':r.get('confidence', {}).get(k, '')})
            writer.writerow(row)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
