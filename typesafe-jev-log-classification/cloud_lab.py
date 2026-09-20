"""Manage only dedicated resources recorded in a private creation manifest."""
import argparse,json,os,re,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT/'.private'

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['create','build-status','deploy','status','cleanup']);p.add_argument('--project',required=True);p.add_argument('--prefix',default='jev-lab-0920');args=p.parse_args()
 if not re.fullmatch('jev-lab-[a-z0-9-]{1,20}',args.prefix):p.error('invalid prefix')
 PRIVATE.mkdir(mode=0o700,exist_ok=True);mp=PRIVATE/(args.prefix+'.json')
 base=['gcloud','--project='+args.project,'--quiet'];region='asia-northeast1'
 def run(*cmd,data=None,check=True):
  r=subprocess.run(base+list(cmd),input=data,capture_output=True,timeout=600)
  if r.returncode and check:
   (PRIVATE/'last-error.txt').write_bytes(r.stderr);raise RuntimeError('gcloud failed; inspect .private/last-error.txt')
  return r
 def read(*cmd):return json.loads(run(*cmd,'--format=json').stdout)
 def save():mp.write_text(json.dumps(state,indent=2)+'\n');mp.chmod(0o600)
 if args.action=='create':
  if mp.exists():raise RuntimeError('manifest already exists')
  for cmd in [('run','services','list','--region='+region),('iam','service-accounts','list'),('artifacts','repositories','list','--location='+region)]:
   if args.prefix in json.dumps(read(*cmd)):raise RuntimeError('prefix collision')
  state={'project':args.project,'prefix':args.prefix,'region':region,'created_utc':datetime.now(timezone.utc).isoformat(),'resources':[]};save()
  def create(kind,name,*cmd,data=None):
   run(*cmd,data=data);state['resources'].append({'kind':kind,'name':name});save();print('Created',kind,name,flush=True)
  enabled=read('services','list','--enabled')
  if not any(x['config']['name']=='secretmanager.googleapis.com' for x in enabled):
   run('services','enable','secretmanager.googleapis.com');state['enabled_secretmanager_api']=True;save();print('Enabled Secret Manager',flush=True)
  for suffix in ['gen','eval']:
   name=args.prefix+'-'+suffix;create('service-account',name,'iam','service-accounts','create',name,'--display-name=Temporary Jev article lab')
  name=args.prefix+'-api-key'
  sys.path.insert(0,str(ROOT));from experiment import key_from_file
  create('secret',name,'secrets','create',name,'--replication-policy=automatic','--data-file=-',data=key_from_file(ROOT/'api.env').encode())
  create('secret',args.prefix+'-denied','secrets','create',args.prefix+'-denied','--replication-policy=automatic','--data-file=-',data=b'non-sensitive-iam-denial-test')
  run('secrets','add-iam-policy-binding',name,'--member=serviceAccount:'+args.prefix+'-eval@'+args.project+'.iam.gserviceaccount.com','--role=roles/secretmanager.secretAccessor')
  create('repository',args.prefix,'artifacts','repositories','create',args.prefix,'--repository-format=docker','--location='+region)
  image=region+'-docker.pkg.dev/'+args.project+'/'+args.prefix+'/app:experiment'
  result=read('builds','submit',str(ROOT/'cloud'),'--tag='+image,'--async')
  state['image']=image;state['build_id']=result['id'];save();print('Build submitted',result['id'],flush=True);return
 if not mp.exists():raise RuntimeError('no manifest')
 state=json.loads(mp.read_text())
 if state['project']!=args.project:raise RuntimeError('project mismatch')
 if args.action=='build-status':
  b=read('builds','describe',state['build_id']);print('build status',b['status'])
  state['build_status']=b['status'];state['build_source']=b.get('source');state['build_results']=b.get('results');save();return
 if args.action=='deploy':
  b=read('builds','describe',state['build_id'])
  if b['status']!='SUCCESS':raise RuntimeError('build is not successful')
  state['build_source']=b.get('source');state['build_results']=b.get('results');save()
  digest=b['results']['images'][0]['digest'];image=state['image'].split(':')[0]+'@'+digest
  for suffix,role,timeout in [('gen','generator','3s'),('eval','evaluator','300s')]:
   name=args.prefix+'-'+suffix
   if state.get(role+'_url'):continue
   env='LAB_ROLE='+role+',LAB_REGION='+region
   if suffix=='gen':env+=',ENABLE_LAB_FAULTS=1,DENIED_SECRET_RESOURCE=projects/'+args.project+'/secrets/'+args.prefix+'-denied/versions/1'
   extra=['--set-env-vars='+env]
   if suffix=='eval':extra+=['--set-secrets=TYPESAFE_API_KEY='+args.prefix+'-api-key:1']
   # Record attempted creation before long-running operation to permit cleanup on partial failures.
   if not any(x['kind']=='service' and x['name']==name for x in state['resources']):
    state['resources'].append({'kind':'service','name':name});save()
   run('run','deploy',name,'--image='+image,'--region='+region,'--service-account='+name+'@'+args.project+'.iam.gserviceaccount.com','--cpu=1','--memory=512Mi','--min-instances=0','--max-instances=1','--concurrency=1','--timeout='+timeout,'--no-allow-unauthenticated','--no-cpu-boost','--execution-environment=gen2',*extra)
   service=read('run','services','describe',name,'--region='+region)
   state[role+'_url']=service['status']['url'];(PRIVATE/(suffix+'-service.json')).write_text(json.dumps(service,indent=2));save();print('Deployed',name,flush=True)
  return
 if args.action=='status':
  for item in state['resources']:print(item['kind'],item['name'])
  return
 if args.action=='cleanup':
  failures=[]
  for item in list(reversed(state['resources'])):
   kind,name=item['kind'],item['name']
   commands={'service':('run','services','delete',name,'--region='+region),'secret':('secrets','delete',name),'repository':('artifacts','repositories','delete',name,'--location='+region),'service-account':('iam','service-accounts','delete',name+'@'+args.project+'.iam.gserviceaccount.com')}
   r=run(*commands[kind],check=False)
   if r.returncode:failures.append(item);(PRIVATE/'cleanup-error.txt').write_bytes(r.stderr)
   else:state['resources'].remove(item);save();print('Deleted',kind,name,flush=True)
  source=(state.get('build_source') or {}).get('storageSource')
  if source and not state.get('build_source_deleted'):
   r=run('storage','rm','gs://'+source['bucket']+'/'+source['object'],check=False)
   if r.returncode:failures.append({'kind':'build-source','name':source['object']})
   else:state['build_source_deleted']=True;save();print('Deleted build source object',flush=True)
  state['cleanup_utc']=datetime.now(timezone.utc).isoformat();state['cleanup_failures']=failures;save()
  if failures:raise RuntimeError('cleanup incomplete')
if __name__=='__main__':main()
