"""Test support: a fake panel that records every request and answers with whatever a test sets."""

import json
import os
import ssl
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from commypanel import Client  # noqa: E402

TOKEN = "7|cpt_secretsecretsecretsecretsecretsecret"
TLS_DIR = os.path.join(HERE, "fixtures", "tls")


class FakePanel:
    """A local HTTP(S) server. ``handler(request, n)`` returns (status, body, headers) and n counts requests."""

    def __init__(self, handler=None, tls=False, cert="server"):
        self.requests = []
        self._lock = threading.Lock()
        self.handler = handler or reply(200, '{"data":[]}')
        panel = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8") if length else ""
                path, _, query = self.path.partition("?")

                with panel._lock:
                    panel.requests.append(
                        {"method": self.command, "path": path, "query": query, "body": body, "headers": dict(self.headers.items())}
                    )
                    n = len(panel.requests)

                status, payload, headers = panel.handler(panel.requests[-1], n)
                raw = payload.encode("utf-8") if isinstance(payload, str) else payload
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))

                for name, value in (headers or {}).items():
                    self.send_header(name, value)

                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_DELETE = _serve

            def log_message(self, *args):  # keep the test output quiet
                pass

        ThreadingHTTPServer.request_queue_size = 128  # many clients at once in the concurrency test
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True

        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(os.path.join(TLS_DIR, cert + ".pem"), os.path.join(TLS_DIR, cert + ".key"))
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)

        self.scheme = "https" if tls else "http"
        self.url = "%s://127.0.0.1:%d" % (self.scheme, self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def last(self):
        return self.requests[-1]


def reply(status, body, headers=None):
    def handler(request, n):
        return status, body, headers

    return handler


class PanelTestCase(unittest.TestCase):
    def panel(self, handler=None, tls=False, cert="server"):
        panel = FakePanel(handler, tls, cert)
        self.addCleanup(panel.close)

        return panel

    def client(self, panel, **options):
        """A client for the fake panel that does not really sleep (the waits are recorded in ``client.waits``)."""
        options.setdefault("allow_http_loopback", True)
        client = Client(panel.url, TOKEN, **options)
        client.waits = []
        client._sleep = client.waits.append

        return client


def dep_json(number=4, status="queued", stage=None, finished=False, succeeded=False, error=None):
    return json.dumps(
        {
            "number": number, "status": status, "stage": stage, "finished": finished, "succeeded": succeeded,
            "commit": "abc123", "commit_message": "Fix", "strategy": "rolling", "is_rollback": False,
            "error": error, "created_at": None, "finished_at": None, "url": "u",
        }
    )
