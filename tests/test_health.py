import json
import socket
import threading
import time
import urllib.request

import uvicorn

from main import app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_health_endpoint():
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    status = None
    body = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                status = response.status
                body = response.read().decode()
            break
        except Exception:
            time.sleep(0.05)

    server.should_exit = True
    thread.join(timeout=5)

    assert status == 200
    assert json.loads(body) == {"status": "healthy"}
