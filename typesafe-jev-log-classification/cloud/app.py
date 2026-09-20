"""Isolated Cloud Run evaluator/fault generator. Cloud Run IAM must protect both."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import platform
import random
import re
import socket
import sqlite3
import ssl
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from experiment import Client, questions, route, stats

BOOT_ID = uuid.uuid4().hex
STARTED = time.monotonic()
ROLE = os.environ.get('LAB_ROLE', 'evaluator')

def emit(message, case_id, severity='INFO'):
    print(json.dumps({'severity':severity,'message':message,'case_id':case_id,'boot_id':BOOT_ID}),flush=True)

def fault(kind):
    if kind == 'database':
        with tempfile.TemporaryDirectory() as directory:
            path = directory+'/lab.db'
            a=sqlite3.connect(path); b=sqlite3.connect(path,timeout=0.1)
            try:
                a.execute('CREATE TABLE events(value TEXT)');a.commit()
                a.execute('BEGIN EXCLUSIVE')
                b.execute("INSERT INTO events VALUES ('test')")
            finally:
                a.rollback();a.close();b.close()
    elif kind == 'dns':
        socket.getaddrinfo('missing.jev-lab.invalid',443)
    elif kind == 'iam':
        # This SA must have NO access to the dedicated test secret.
        # Only the HTTP status is logged; the Google error body/token is not logged.
        resource=os.environ['DENIED_SECRET_RESOURCE']
        req=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',headers={'Metadata-Flavor':'Google'})
        with urllib.request.urlopen(req,timeout=5) as response: token=json.load(response)['access_token']
        req=urllib.request.Request('https://secretmanager.googleapis.com/v1/'+resource+':access',headers={'Authorization':'Bearer '+token})
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                response.read()  # Never persist or log the returned bytes.
            raise RuntimeError('Unexpected success: test identity has secret access')
        except urllib.error.HTTPError as exc:
            status=exc.code
            exc.close()
        if status != 403: raise RuntimeError('Expected IAM denial; received HTTP '+str(status))
        raise PermissionError('Secret Manager access denied: HTTP 403 (test identity lacks secret access)')
    elif kind == 'timeout':
        time.sleep(7)  # Deploy fault service with request timeout=3s.
    elif kind == 'oom':
        # Only on the disposable generator; NEVER on evaluator.
        allocations=[]
        for _ in range(48): allocations.append(bytearray(16*1024*1024))
    elif kind != 'normal':
        raise ValueError('unknown fault kind')

def network_baseline(count=10):
    rows=[]
    context=ssl.create_default_context()
    for _ in range(count):
        start=time.perf_counter()
        addresses=socket.getaddrinfo('api.typesafe.ai',443,type=socket.SOCK_STREAM)
        resolved=time.perf_counter()
        family,kind,proto,_,address=addresses[0]
        with socket.socket(family,kind,proto) as raw:
            raw.settimeout(10)
            raw.connect(address)
            connected=time.perf_counter()
            with context.wrap_socket(raw,server_hostname='api.typesafe.ai'):
                secured=time.perf_counter()
        rows.append({'dns_ms':(resolved-start)*1000,'tcp_ms':(connected-resolved)*1000,'tls_ms':(secured-connected)*1000})
    return rows

def benchmark(body):
    states=body.get('cases',[])
    repetitions=body.get('repetitions',50)
    if not isinstance(repetitions,int) or not 0<=repetitions<=50: raise ValueError('repetitions must be 0..50')
    if not isinstance(states,list) or not 1<=len(states)<=40: raise ValueError('cases must contain 1..40 entries')
    if any(not isinstance(c,dict) or not isinstance(c.get('id'),str) or not isinstance(c.get('state'),str) or len(c['state'])>20000 for c in states):
        raise ValueError('invalid cases')
    anchor=states[0]['state']
    rows=[]
    network=network_baseline()
    client=Client(os.environ['TYPESAFE_API_KEY'])
    def call(phase, case, count):
        row={'at':datetime.now(timezone.utc).isoformat(),'phase':phase,'case_id':case['id'],'question_count':count}
        row.update(client.call(case['state'],questions(count),'jev-1.13.0'))
        if row['ok'] and count>=3: row['route']=route(row['response'])
        rows.append(row)
    try:
        for n in (1,3,10):call('warmup',states[0],n)
        for case in states:call('classification',case,3)
        rng=random.Random(920)
        for _ in range(repetitions):
            order=[1,3,10];rng.shuffle(order)
            for n in order:call('latency',states[0],n)
    finally:client.close()
    return {'network_baseline':network,'environment':{'region_configured':os.getenv('LAB_REGION'),'service':os.getenv('K_SERVICE'),'revision':os.getenv('K_REVISION'),'python':platform.python_version(),'boot_id':BOOT_ID,'process_age_seconds':time.monotonic()-STARTED},'benchmark_state_chars':len(anchor),'rows':rows,'latency':{str(n):stats([r['elapsed_ms'] for r in rows if r['ok'] and r['phase']=='latency' and r['question_count']==n]) for n in (1,3,10)}}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,body):
        data=json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if self.path=='/health':
            self.send(200,{'ok':True,'boot_id':BOOT_ID,'process_age_seconds':time.monotonic()-STARTED})
        else:self.send(404,{'error':'not found'})
    def do_POST(self):
        parsed=urllib.parse.urlparse(self.path)
        if parsed.path.startswith('/fault/') and ROLE=='generator' and os.getenv('ENABLE_LAB_FAULTS')=='1':
            kind=parsed.path.split('/')[-1]
            if kind not in {'database','dns','iam','timeout','oom','normal'}:self.send(400,{'error':'unknown fault'});return
            case=urllib.parse.parse_qs(parsed.query).get('case',['unspecified'])[0]
            if not re.fullmatch('[a-z0-9-]{1,64}',case):self.send(400,{'error':'invalid case'});return
            emit('Test request started',case)
            try:
                fault(kind)
                emit('Request completed successfully: HTTP 200',case)
                self.send(200,{'ok':True,'case_id':case})
            except Exception:
                trace=re.sub(r'File "[^"]*/([^/\"]+)"',r'File "\1"',traceback.format_exc())
                emit(trace,case,'ERROR');self.send(500,{'ok':False,'case_id':case})
        elif parsed.path=='/benchmark' and ROLE=='evaluator':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=512000:raise ValueError('invalid request size')
                body=json.loads(self.rfile.read(size))
                result=benchmark(body)
                self.send(200,result)
            except (ValueError,KeyError,TypeError):self.send(400,{'error':'invalid benchmark input or configuration'})
        else:self.send(404,{'error':'not found'})

if __name__=='__main__':
    emit('Container ready','startup')
    HTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
