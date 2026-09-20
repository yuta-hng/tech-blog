"""Create real local failures; these are NOT Cloud Run / Cloud Logging logs."""
import http.client
import json
import socket
import sqlite3
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/slow':
            time.sleep(0.3)
        status = 401 if self.path == '/private' else 200
        self.send_response(status)
        self.end_headers()
    def log_message(self, *args):
        pass


def generate():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cases = []
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'test.db')
        a, b = sqlite3.connect(path), sqlite3.connect(path, timeout=0.02)
        a.execute('CREATE TABLE events (value TEXT)'); a.commit()
        try:
            for kind, expected in [('application','application_error'), ('database','database_error'), ('dns','network_error'), ('timeout','network_error'), ('authentication','authentication_error'), ('normal','normal')]:
                for i in range(5):
                    conn = None
                    prefix = 'Request processing log\n'
                    try:
                        if kind == 'application':
                            int('invalid-input-' + str(i))
                        elif kind == 'database':
                            a.execute('BEGIN EXCLUSIVE')
                            try:
                                b.execute('INSERT INTO events VALUES (?)', (str(i),))
                            finally:
                                a.rollback()
                        elif kind == 'dns':
                            socket.getaddrinfo('missing-' + str(i) + '.invalid', 443)
                        else:
                            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=0.05)
                            endpoint = {'timeout':'/slow', 'authentication':'/private', 'normal':'/health'}[kind]
                            prefix += f'GET {endpoint}\n'
                            conn.request('GET', endpoint)
                            response = conn.getresponse()
                            response.read()
                            prefix += f'HTTP {response.status} {response.reason}\n'
                            if response.status == 401:
                                prefix += 'Request rejected: credentials required.\n'
                            else:
                                prefix += 'Request completed successfully.\n'
                    except Exception:
                        # Strip directory paths but retain real frame names and exception text.
                        trace = traceback.format_exc()
                        import re
                        trace = re.sub(r'File "[^"]*/([^/\"]+)"', r'File "\1"', trace)
                        prefix += trace
                    finally:
                        if conn: conn.close()
                    cases.append({'id':f'{kind}-{i+1:02d}', 'expected':expected, 'source':'local_fault_injection', 'state':prefix})
        finally:
            a.close(); b.close(); server.shutdown(); server.server_close()
    return cases

if __name__ == '__main__':
    target = Path(__file__).with_name('cases.json')
    if target.exists():
        raise SystemExit('cases.json exists; move it before regenerating fixed inputs')
    target.write_text(json.dumps(generate(), ensure_ascii=False, indent=2)+'\n')
    print(target.name)
