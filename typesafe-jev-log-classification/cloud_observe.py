"""Read startup metrics and IAM configuration for the dedicated lab only."""
import json,subprocess,urllib.request,urllib.parse
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
state=json.loads((ROOT/'.private/jev-lab-0920.json').read_text());project=state['project'];prefix=state['prefix']
base=['gcloud','--project='+project,'--quiet']
token=subprocess.check_output(base+['auth','print-access-token']).decode().strip()
end=datetime.now(timezone.utc);start=end-timedelta(minutes=30)
query=urllib.parse.urlencode({'filter':'metric.type="run.googleapis.com/container/startup_latencies" AND resource.labels.service_name="'+prefix+'-eval"','interval.startTime':start.isoformat(),'interval.endTime':end.isoformat(),'view':'FULL'})
req=urllib.request.Request('https://monitoring.googleapis.com/v3/projects/'+project+'/timeSeries?'+query,headers={'Authorization':'Bearer '+token})
with urllib.request.urlopen(req,timeout=30) as response:body=json.load(response)
(ROOT/'.private/startup-metric-raw.json').write_text(json.dumps(body,indent=2))
series=[{'metric_labels':x.get('metric',{}).get('labels',{}),'points':x.get('points',[])} for x in body.get('timeSeries',[])]
(ROOT/'results/cloud-startup-metric.json').write_text(json.dumps({'metric':'run.googleapis.com/container/startup_latencies','unit':'ms','series':series},indent=2)+'\n')
print('startup metric series',len(series))
for entry in series:
 for point in entry['points']:
  d=point.get('value',{}).get('distributionValue',{});print('startup count',d.get('count'),'mean_ms',d.get('mean'))
for suffix in ['gen','eval']:
 policy=json.loads(subprocess.check_output(base+['run','services','get-iam-policy',prefix+'-'+suffix,'--region=asia-northeast1','--format=json']))
 assert not any(m in ['allUsers','allAuthenticatedUsers'] for b in policy.get('bindings',[]) for m in b.get('members',[]))
 print(suffix,'no public invoker binding')
