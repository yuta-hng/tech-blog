import os
import time

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def index():
    work_ms = max(0, int(request.args.get("work_ms", os.getenv("WORK_MS", "100"))))
    time.sleep(work_ms / 1000)
    return jsonify(ok=True, work_ms=work_ms)


@app.get("/healthz")
def healthz():
    return {"ok": True}
