import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(__file__))
import healthcheck  # noqa: E402


def info(state="proposing", age=3, seq=100, **extra):
    d = {"server_state": state, "validated_ledger": {"age": age, "seq": seq}}
    d.update(extra)
    return d


class EvaluateTests(unittest.TestCase):
    def test_proposing_and_fresh_is_ok(self):
        ok, reason = healthcheck.evaluate(info())
        self.assertTrue(ok)
        self.assertIn("ledger 100", reason)

    def test_full_is_not_ok(self):
        # The public port reports "full" for a healthy validator -- this check
        # must be pointed at the admin port, and treats "full" as a failure.
        ok, reason = healthcheck.evaluate(info(state="full"))
        self.assertFalse(ok)
        self.assertIn("server_state=full", reason)

    def test_stale_ledger_is_not_ok(self):
        ok, reason = healthcheck.evaluate(info(age=31))
        self.assertFalse(ok)
        self.assertIn("31s old", reason)

    def test_age_at_limit_is_ok(self):
        self.assertTrue(healthcheck.evaluate(info(age=30))[0])

    def test_missing_validated_ledger(self):
        ok, reason = healthcheck.evaluate({"server_state": "proposing"})
        self.assertFalse(ok)
        self.assertEqual(reason, "no validated ledger")

    def test_amendment_blocked_wins(self):
        ok, reason = healthcheck.evaluate(info(amendment_blocked=True))
        self.assertFalse(ok)
        self.assertEqual(reason, "amendment blocked")


class _Recorder(BaseHTTPRequestHandler):
    """Plays both xrpld admin RPC (POST /) and Healthchecks.io (POST /hc...)."""

    rpc_response = None
    pings = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if self.path.startswith("/hc"):
            type(self).pings.append((self.path, body))
            payload = b"OK"
        else:
            payload = json.dumps(type(self).rpc_response).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class MainTests(unittest.TestCase):
    def setUp(self):
        _Recorder.pings = []
        self.srv = HTTPServer(("127.0.0.1", 0), _Recorder)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addr = f"127.0.0.1:{self.srv.server_port}"
        self.env = dict(os.environ)
        os.environ["HC_PING_URL"] = f"http://{self.addr}/hc/uuid"
        os.environ["XRPLD_ADMIN_RPC"] = self.addr

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.clear()
        os.environ.update(self.env)

    def test_healthy_pings_success_endpoint(self):
        _Recorder.rpc_response = {"result": {"info": info()}}
        self.assertEqual(healthcheck.main(), 0)
        self.assertEqual(_Recorder.pings[0][0], "/hc/uuid")

    def test_unhealthy_pings_fail_with_reason(self):
        _Recorder.rpc_response = {"result": {"info": info(state="connected")}}
        healthcheck.main()
        path, body = _Recorder.pings[0]
        self.assertEqual(path, "/hc/uuid/fail")
        self.assertIn("server_state=connected", body)

    def test_rpc_down_reports_generic_reason_without_address(self):
        os.environ["XRPLD_ADMIN_RPC"] = "127.0.0.1:1"  # nothing listens here
        healthcheck.main()
        path, body = _Recorder.pings[0]
        self.assertEqual(path, "/hc/uuid/fail")
        self.assertIn("unreachable", body)
        self.assertNotIn("127.0.0.1", body)

    def test_undeliverable_ping_does_not_crash(self):
        _Recorder.rpc_response = {"result": {"info": info()}}
        os.environ["HC_PING_URL"] = "http://127.0.0.1:1/hc/uuid"
        self.assertEqual(healthcheck.main(), 0)

    def test_missing_ping_url_exits_2(self):
        del os.environ["HC_PING_URL"]
        self.assertEqual(healthcheck.main(), 2)


if __name__ == "__main__":
    unittest.main()
