"""TypeSafe Jev measurements using stdlib only; preserves each response as JSONL."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import time

ROOT = Path(__file__).resolve().parent
QUESTIONS = {
    'category': {'type':'choice', 'instructions':'Classify the primary problem directly evidenced in this log. A database locking error belongs to database_error. A socket or DNS timeout belongs to network_error.', 'criteria': {
        'application_error':'Application code failure, such as parsing invalid input or an unhandled exception unrelated to a dependency.',
        'network_error':'DNS resolution, socket connection, or network read failure or timeout.',
        'authentication_error':'A request was rejected because credentials or authorization are missing or invalid.',
        'database_error':'A database operation failed because of database locking, query errors, or connection pool exhaustion.',
        'normal':'Successful request with no evidence of failure.'}},
    'severity': {'type':'score','instructions':'Rate the operational impact supported by this log only. Do not assume an outage or data loss without evidence.', 'criteria':[
        'A successful operation with no error or user impact.',
        'An individual request failed or was rejected; no evidence of wider outage or data loss.',
        'Repeated failures or an unavailable dependency disrupt multiple requests.',
        'Explicit evidence of a service-wide outage, data loss, or an active security breach.']},
    'needs_human_review': {'type':'noul','instructions':'Does this log show a failure or uncertainty that a human operator should investigate?'}
}
EXTRA = {
    'has_exception':'Does the log contain a Python exception traceback?',
    'is_timeout':'Does the log explicitly show a timeout?',
    'is_dns':'Does the log show failure of DNS name resolution?',
    'is_database':'Does the log show a failed database operation?',
    'is_denied':'Does the log show an HTTP request rejected for missing credentials?',
    'is_success':'Does the log show a successful HTTP response?',
    'has_data_loss':'Does the log explicitly show data loss?'
}

def questions(count):
    if count == 1: return {'category':QUESTIONS['category']}
    if count == 3: return QUESTIONS.copy()
    if count == 10: return {**QUESTIONS, **{k:{'type':'noul','instructions':v} for k,v in EXTRA.items()}}
    raise ValueError('count must be 1, 3, or 10')

def key_from_file(path):
    key = os.getenv('TYPESAFE_API_KEY')
    if key: return key
    raw = path.read_text().strip()
    if '=' not in raw and '\n' not in raw: return raw
    for line in raw.splitlines():
        if line.startswith('TYPESAFE_API_KEY='):
            return line.split('=',1)[1].strip().strip('\"\'')
    raise ValueError('TYPESAFE_API_KEY not found')

def validate(response, requested):
    answers = response['answers']
    if set(answers) != set(requested): raise ValueError('unexpected answer keys')
    for name, q in requested.items():
        a = answers[name]
        if a['type'] != q['type']: raise ValueError('unexpected answer type')
        if q['type'] == 'noul':
            if not 0 <= a['noul'] <= 1: raise ValueError('invalid probability')
        else:
            expected = set(q['criteria']) if q['type'] == 'choice' else {str(i) for i in range(len(q['criteria']))}
            p = a['probabilities']
            if set(p) != expected or any(not 0 <= v <= 1 for v in p.values()) or not math.isclose(sum(p.values()), 1, abs_tol=0.02):
                raise ValueError('invalid distribution')
            if not 0 <= a['confidence'] <= 1: raise ValueError('invalid confidence')
            if q['type'] == 'choice' and a['choice'] not in expected: raise ValueError('invalid choice')
            if q['type'] == 'score' and not 0 <= a['score'] <= len(expected)-1: raise ValueError('invalid score')

def route(response):
    a = response['answers']
    # Both confidence values are distribution statistics, NOT accuracy guarantees.
    if min(a['category']['confidence'], a['severity']['confidence']) < 0.7:
        return 'human_review'
    if a['severity']['score'] >= 2.5 and a['category']['confidence'] >= 0.9:
        return 'escalation_candidate'
    # Noul returns a probability, not a confidence property.
    if a['needs_human_review']['noul'] >= 0.5:
        return 'human_review'
    return 'record_only'

class Client:
    def __init__(self, key):
        self.key = key
        self.conn = http.client.HTTPSConnection('api.typesafe.ai', timeout=30)
    def call(self, state, qs, model):
        payload = json.dumps({'model':model, 'state':state, 'questions':qs}).encode()
        start = time.perf_counter()
        try:
            self.conn.request('POST','/v1/systemone',body=payload,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
            r = self.conn.getresponse()
            raw = r.read()
            elapsed = (time.perf_counter()-start)*1000
            if r.status != 200:
                return {'ok':False, 'status':r.status, 'elapsed_ms':elapsed}
            response = json.loads(raw)
            validate(response, qs)
            return {'ok':True,'status':r.status,'elapsed_ms':elapsed,'response':response}
        except Exception as e:
            self.conn.close()
            return {'ok':False,'error_type':type(e).__name__,'elapsed_ms':(time.perf_counter()-start)*1000}
    def close(self): self.conn.close()

def stats(values):
    return {'n':len(values),'median_ms':statistics.median(values),'p95_ms':sorted(values)[math.ceil(0.95*len(values))-1], 'min_ms':min(values),'max_ms':max(values)} if values else {'n':0}

def summarize(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    classified = [r for r in rows if r['phase']=='classification' and r['ok']]
    total = sum(r.get('response',{}).get('usage',{}).get('input_tokens',0) for r in rows)
    result = {'requests':len(rows),'successes':sum(r['ok'] for r in rows),'failures':sum(not r['ok'] for r in rows),
        'models':sorted({r['response']['model'] for r in rows if r['ok']}),
        'classification':{'n':len(classified),'matches':sum(r['response']['answers']['category']['choice']==r['expected'] for r in classified), 'routes':dict(Counter(r['route'] for r in classified))},
        'latency':{str(n):stats([r['elapsed_ms'] for r in rows if r['phase']=='latency' and r['question_count']==n and r['ok']]) for n in (1,3,10)},
        'input_tokens':total,'estimated_usd_at_0_042_per_million':total*0.042/1_000_000}
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument('--key-file',type=Path,default=ROOT/'api.env'); p.add_argument('--repetitions',type=int,default=50); p.add_argument('--summarize',type=Path); args=p.parse_args()
    if args.summarize:
        print(json.dumps(summarize(args.summarize),indent=2)); return
    client=Client(key_from_file(args.key_file)); cases=json.loads((ROOT/'cases.json').read_text()); state=cases[5]['state']
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'); output=ROOT/'results'/f'measurements-{stamp}.jsonl'; output.parent.mkdir(exist_ok=True)
    metadata={'python':platform.python_version(),'platform':platform.system(),'location':'local_execution_environment_not_verified','connection':'sequential HTTPS keep-alive','retries':0,'requested_model':'jev-1.13.0','repetitions':args.repetitions,'seed':920,'cases_sha256':hashlib.sha256((ROOT/'cases.json').read_bytes()).hexdigest(),'benchmark_case_id':cases[5]['id'],'benchmark_state_chars':len(state),'questions':{str(n):questions(n) for n in (1,3,10)}}
    output.with_suffix('.meta.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    with output.open('w') as f:
        def run(phase, case, count):
            row={'at':datetime.now(timezone.utc).isoformat(),'phase':phase,'case_id':case['id'],'question_count':count,'expected':case['expected']}
            row.update(client.call(case['state'],questions(count),'jev-1.13.0'))
            if row['ok'] and count>=3: row['route']=route(row['response'])
            f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush()
            if not row['ok']: print('request failed',row.get('status',row.get('error_type')),flush=True)
            return row
        for count in (1,3,10): run('warmup',cases[5],count)
        for case in cases: run('classification',case,3)
        rng=random.Random(920)
        for i in range(args.repetitions):
            order=[1,3,10]; rng.shuffle(order)
            for count in order: run('latency',cases[5],count)
            if (i+1)%10==0: print('completed latency rounds',i+1,flush=True)
    client.close()
    summary=summarize(output); output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(output.name); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
