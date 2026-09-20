"""Collect dedicated lab logs; persist sanitized inputs before calling TypeSafe."""
import argparse,json,os,re,subprocess,time,urllib.request,urllib.error
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT/'.private'
RESULTS=ROOT/'results'

def now():return datetime.now(timezone.utc).isoformat()
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['inject','collect','benchmark','smoke']);p.add_argument('--prefix',default='jev-lab-0920');args=p.parse_args()
 manifest=json.loads((PRIVATE/(args.prefix+'.json')).read_text());project=manifest['project'];base=['gcloud','--project='+project,'--quiet']
 def gcloud(*cmd):
  r=subprocess.run(base+list(cmd),capture_output=True,check=True);return r.stdout
 def token():return gcloud('auth','print-identity-token').decode().strip()
 identity=token()
 def call(url,data=None,timeout=320):
  req=urllib.request.Request(url,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+identity,'Content-Type':'application/json'})
  start=time.perf_counter()
  try:
   with urllib.request.urlopen(req,timeout=timeout) as r:status=r.status;raw=r.read()
  except urllib.error.HTTPError as e:status=e.code;raw=e.read()
  elapsed=(time.perf_counter()-start)*1000
  try:body=json.loads(raw)
  except (json.JSONDecodeError,UnicodeDecodeError):body={'text':raw.decode(errors='replace')[:2000]}
  return {'status':status,'elapsed_ms':elapsed,'body':body}
 if args.action=='smoke':
  r=call(manifest['evaluator_url']+'/benchmark',{'cases':[{'id':'smoke','state':'HTTP 200: request completed successfully.'}],'repetitions':0})
  (PRIVATE/'cloud-smoke.json').write_text(json.dumps(r,indent=2));print('evaluator HTTP',r['status']);return
 if args.action=='inject':
  path=PRIVATE/'injection-trials.jsonl'
  if path.exists():raise RuntimeError('trials already exist')
  url=manifest['generator_url']
  health=call(url+'/health');(PRIVATE/'generator-first-health.json').write_text(json.dumps(health,indent=2))
  if health['status']!=200:raise RuntimeError('generator health failed')
  # Preassigned taxonomy, BEFORE any Jev call: request timeout -> network symptom.
  categories={'database':'database_error','dns':'network_error','iam':'authentication_error','timeout':'network_error','oom':'application_error','normal':'normal'}
  with path.open('w') as out:
   for kind,expected in categories.items():
    for i in range(5):
     case=f'{kind}-{i+1:02d}'
     pre=call(url+'/health')
     if pre['status']!=200:raise RuntimeError('unhealthy generator before '+case)
     start=now();result=call(url+'/fault/'+kind+'?case='+case,{},timeout=40);end=now()
     record={'id':case,'kind':kind,'expected':expected,'start':start,'end':end,'health':pre,'result':result}
     out.write(json.dumps(record)+'\n');out.flush();print(case,'HTTP',result['status'],flush=True)
     # Timeout handler keeps executing after the gateway sends 504. Wait for its completion.
     time.sleep(8 if kind=='timeout' else 3 if kind=='oom' else 0.3)
  return
 if args.action=='collect':
  trials=[json.loads(l) for l in (PRIVATE/'injection-trials.jsonl').read_text().splitlines()]
  start=(datetime.fromisoformat(trials[0]['start'])-timedelta(minutes=1)).isoformat()
  query='resource.type="cloud_run_revision" AND resource.labels.service_name="'+args.prefix+'-gen" AND timestamp>="'+start+'"'
  entries=json.loads(gcloud('logging','read',query,'--limit=2000','--order=asc','--format=json'))
  (PRIVATE/'generator-logs.json').write_text(json.dumps(entries,indent=2))
  cases=[]
  def dt(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
  for t in trials:
   ident=t['id'];kind=t['kind'];parts=[]
   if kind in {'database','dns','iam','normal'}:
    matches=[x for x in entries if x.get('jsonPayload',{}).get('case_id')==ident]
    for x in matches:
     payload=x['jsonPayload'];message=payload.get('message','')
     if message=='Test request started':continue
     if kind=='normal' and 'completed successfully' not in message:continue
     if kind!='normal' and x.get('severity',payload.get('severity'))!='ERROR':continue
     parts.append(message)
   elif kind=='timeout':
    matches=[x for x in entries if ('case='+ident) in x.get('httpRequest',{}).get('requestUrl','') and x.get('httpRequest',{}).get('status')==504]
    for x in matches:
     request=x['httpRequest'];parts.append(json.dumps({'severity':x.get('severity'),'httpRequest':{k:request[k] for k in ['requestMethod','status','latency','protocol'] if k in request}},ensure_ascii=False))
     if x.get('textPayload'):parts.append(x['textPayload'])
   elif kind=='oom':
    markers=[x for x in entries if x.get('jsonPayload',{}).get('case_id')==ident and x.get('jsonPayload',{}).get('message')=='Test request started']
    if len(markers)!=1:raise RuntimeError('ambiguous OOM start marker')
    marker=markers[0];lo=dt(marker['timestamp']);hi=lo+timedelta(seconds=10)
    instance=marker.get('labels',{}).get('instanceId')
    matches=[x for x in entries if 'memory' in x.get('textPayload','').lower() and lo<=dt(x['timestamp'])<=hi and x.get('labels',{}).get('instanceId')==instance]
    for x in matches:parts.append(x['textPayload'])
   if not parts:raise RuntimeError('No qualifying actual log for '+ident)
   state='\n'.join(parts)
   state=state.replace(project,'PROJECT_ID')
   state=re.sub(r'https://[^\s\"<>]+\.run\.app[^\s\"<>]*','CLOUD_RUN_URL',state)
   if project in state or '@' in state or 'Bearer ' in state:raise RuntimeError('sanitization check failed')
   cases.append({'id':ident,'expected':t['expected'],'source':'cloud_logging_fault_injection','state':state})
  path=RESULTS/'cloud-cases.json'
  if path.exists():raise RuntimeError('fixed cloud cases already exist')
  path.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n');print('Saved actual Cloud Logging inputs:',len(cases))
  for c in cases[::5]:print(c['id'],len(c['state']),c['state'][-180:])
  return
 if args.action=='benchmark':
  cases=json.loads((RESULTS/'cloud-cases.json').read_text())
  payload={'cases':[{'id':c['id'],'state':c['state']} for c in cases],'repetitions':50}
  stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
  result=call(manifest['evaluator_url']+'/benchmark',payload)
  (PRIVATE/('cloud-benchmark-'+stamp+'.json')).write_text(json.dumps(result,indent=2))
  if result['status']!=200:print('benchmark HTTP',result['status']);return
  body=result['body'];expected={c['id']:c['expected'] for c in cases}
  for row in body['rows']:row['expected']=expected[row['case_id']]
  # Service and revision are dedicated lab names, not project/account identifiers.
  (RESULTS/('cloud-benchmark-'+stamp+'.json')).write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
  print('Cloud benchmark saved',stamp)
  print(json.dumps(body['latency'],indent=2))
  classifications=[x for x in body['rows'] if x['phase']=='classification']
  for row in classifications[::5]:print(row['case_id'],row.get('response',{}).get('answers',{}))
if __name__=='__main__':main()
