import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, jsonify


app = Flask(__name__)

_app_initialized_at = datetime.now(timezone.utc).isoformat()
_app_initialized_ns = time.monotonic_ns()
_process_id = uuid4().hex
_request_count = 0
_request_count_lock = threading.Lock()


@app.get("/")
def index():
    global _request_count

    with _request_count_lock:
        _request_count += 1
        request_index = _request_count

    return jsonify(
        ok=True,
        app_initialized_at=_app_initialized_at,
        app_uptime_ms=round(
            (time.monotonic_ns() - _app_initialized_ns) / 1_000_000,
            3,
        ),
        process_id=_process_id,
        request_index=request_index,
    )
