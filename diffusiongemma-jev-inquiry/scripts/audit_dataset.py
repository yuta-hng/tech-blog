#!/usr/bin/env python3
"""Validate the attached fixtures locally. No model requests are made."""
import argparse
import collections
import csv
import hashlib
import json
import statistics
from pathlib import Path


def audit(json_path, csv_path):
    raw = json_path.read_bytes()
    data = json.loads(raw)
    items = data['items']
    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    issues = []
    for item in items:
        ident = item.get('id', '<missing>')
        if set(item) != {'id', 'text', 'labels', 'tricky', 'note'}:
            issues.append(f'{ident}: unexpected/missing item fields')
        labels = item.get('labels', {})
        if set(labels) != {'department', 'severity', 'needsHuman'}:
            issues.append(f'{ident}: unexpected/missing label fields')
        if labels.get('department') not in data['questions']['department']['criteria']:
            issues.append(f'{ident}: unknown department')
        if type(labels.get('severity')) is not int or labels['severity'] not in (0, 1, 2):
            issues.append(f'{ident}: invalid severity')
        for key, value in [('needsHuman', labels.get('needsHuman')), ('tricky', item.get('tricky'))]:
            if type(value) is not bool:
                issues.append(f'{ident}: {key} must be a boolean')
        if not isinstance(item.get('text'), str) or not item['text'].strip():
            issues.append(f'{ident}: missing text')
    for key in ('id', 'text'):
        duplicates = [k for k, n in collections.Counter(x.get(key) for x in items).items() if n > 1]
        if duplicates:
            issues.append(f'duplicate {key}: {duplicates}')
    expected = [dict(id=x['id'], **{k: str(v) for k, v in x['labels'].items()},
                     tricky=str(x['tricky']), note=x['note'], text=x['text']) for x in items]
    if rows != expected:
        issues.append('JSON and CSV differ in content or order')
    lengths = [len(x['text']) for x in items]
    result = {
        'model_inference_performed': False,
        'dataset_sha256': hashlib.sha256(raw).hexdigest(),
        'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'count': len(items), 'csv_count': len(rows), 'structural_issues': issues,
        'label_counts': {k: dict(collections.Counter(x['labels'][k] for x in items))
                         for k in ('department', 'severity', 'needsHuman')},
        'tricky_count': sum(x['tricky'] for x in items),
        'text_chars': {'min': min(lengths), 'median': statistics.median(lengths), 'max': max(lengths)},
        'per_department': {},
        'severity2_needsHuman_false': sum(x['labels']['severity'] == 2 and not x['labels']['needsHuman'] for x in items),
        'all_id_prefixes_reveal_department': all(x['id'][0].lower() == x['labels']['department'][0] for x in items),
    }
    for dep in data['questions']['department']['criteria']:
        subset = [x for x in items if x['labels']['department'] == dep]
        result['per_department'][dep] = {
            'n': len(subset),
            'severity': dict(collections.Counter(x['labels']['severity'] for x in subset)),
            'needsHuman': dict(collections.Counter(x['labels']['needsHuman'] for x in subset)),
            'tricky': sum(x['tricky'] for x in subset),
        }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', type=Path, default=Path(__file__).resolve().parents[1] / 'data/inquiry_testset.json')
    parser.add_argument('--csv', type=Path, default=Path(__file__).resolve().parents[1] / 'data/inquiry_testset.csv')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.json, args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result['structural_issues']))
