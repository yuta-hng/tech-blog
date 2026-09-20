"""Recompute the article's Cloud Run figures without network access."""
from collections import Counter
import hashlib,json,statistics
from pathlib import Path
from experiment import stats
ROOT=Path(__file__).resolve().parent

def summarize():
 r=ROOT/'results';path=r/'cloud-benchmark-20260920-142504.json';body=json.loads(path.read_text());rows=body['rows'];cases=json.loads((r/'cloud-cases.json').read_text());smoke=json.loads((r/'cloud-smoke.json').read_text())['body']['rows']
 successful=[x for x in rows if x['ok']];cs=[x for x in successful if x['phase']=='classification']
 groups={}
 for kind in ['database','dns','iam','timeout','oom','normal']:
  entries=[x for x in cs if x['case_id'].startswith(kind+'-')]
  groups[kind]={'n':len(entries),'matches':sum(x['expected']==x['response']['answers']['category']['choice'] for x in entries),'confidence_min':min(x['response']['answers']['category']['confidence'] for x in entries),'confidence_max':max(x['response']['answers']['category']['confidence'] for x in entries)}
 points=[p for series in json.loads((r/'cloud-startup-metric.json').read_text())['series'] for p in series['points']]
 startup=[p['value']['distributionValue'] for p in points if int(p['value'].get('distributionValue',{}).get('count',0))>0]
 input_main=sum(x['response']['usage']['input_tokens'] for x in successful);input_smoke=sum(x['response']['usage']['input_tokens'] for x in smoke if x['ok'])
 result={'benchmark_file':path.name,'requests':len(rows),'successes':len(successful),'failures':len(rows)-len(successful),'models':sorted({x['response']['model'] for x in successful}),'classification':{'n':len(cs),'matches':sum(x['expected']==x['response']['answers']['category']['choice'] for x in cs),'groups':groups,'routes':dict(Counter(x['route'] for x in cs))},'latency':{str(n):stats([x['elapsed_ms'] for x in successful if x['phase']=='latency' and x['question_count']==n]) for n in [1,3,10]},'network_median_ms':{k:statistics.median(x[k] for x in body['network_baseline']) for k in ['dns_ms','tcp_ms','tls_ms']},'startup':{'count':sum(int(x['count']) for x in startup),'mean_ms':sum(int(x['count'])*x['mean'] for x in startup)/sum(int(x['count']) for x in startup) if startup else None},'cases':{'count':len(cases),'unique_states':len(set(x['state'] for x in cases)),'min_chars':min(len(x['state']) for x in cases),'median_chars':statistics.median(len(x['state']) for x in cases),'max_chars':max(len(x['state']) for x in cases),'sha256':hashlib.sha256((r/'cloud-cases.json').read_bytes()).hexdigest()},'input_tokens':{'main':input_main,'smoke':input_smoke,'cloud_total':input_main+input_smoke},'estimated_cloud_api_usd_at_0_042_per_million':(input_main+input_smoke)*0.042/1_000_000}
 assert result['latency']==body['latency']
 return result
if __name__=='__main__':print(json.dumps(summarize(),indent=2))
