#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 curl dnsutils
install -d /opt/psc-lab
cat > /opt/psc-lab/server.py <<'PY'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"message": "psc-lab-ok", "peer_ip": self.client_address[0]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
PY
cat > /etc/systemd/system/psc-lab.service <<'UNIT'
[Unit]
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/psc-lab/server.py
User=nobody
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now psc-lab.service
touch /opt/psc-lab/ready
