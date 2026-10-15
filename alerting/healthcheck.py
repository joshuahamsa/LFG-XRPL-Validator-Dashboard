#!/usr/bin/env python3
"""Dead-man's-switch ping for off-host outage alerting.

Run every minute by validator-healthcheck.timer. Checks the validator over the
admin RPC and pings Healthchecks.io:

  healthy   -> GET  $HC_PING_URL           (resets the grace timer)
  unhealthy -> POST $HC_PING_URL/fail      (body = reason, alerts immediately)

If the WAN, the host, or this timer dies, pings simply stop and Healthchecks.io
alerts after the check's grace period. That is the whole point: the alert never
depends on this box being able to send anything.

The reason string ends up in a PUBLIC GitHub issue (via the outage-tracker
workflow), so it must never contain IPs, keys, or hostnames.
"""
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MAX_LEDGER_AGE = 30  # seconds; ledgers close every ~3-4s
RPC_TIMEOUT = 10
PING_TIMEOUT = 10


def evaluate(info, max_ledger_age=DEFAULT_MAX_LEDGER_AGE):
    """Return (ok, reason) for a server_info `info` dict."""
    if info.get("amendment_blocked"):
        return False, "amendment blocked"
    state = info.get("server_state")
    if state != "proposing":
        return False, f"server_state={state or 'unknown'} (expected proposing)"
    ledger = info.get("validated_ledger")
    if not ledger:
        return False, "no validated ledger"
    age = ledger.get("age")
    if age is None:
        return False, "validated ledger age unknown"
    if int(age) > max_ledger_age:
        return False, f"validated ledger is {int(age)}s old (limit {max_ledger_age}s)"
    return True, f"proposing, ledger {ledger.get('seq')} age {int(age)}s"


def fetch_server_info(admin_rpc):
    req = urllib.request.Request(
        f"http://{admin_rpc}",
        data=json.dumps({"method": "server_info"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=RPC_TIMEOUT) as resp:
        return json.load(resp)["result"]["info"]


def check(admin_rpc, max_ledger_age):
    try:
        info = fetch_server_info(admin_rpc)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        # Deliberately generic: the exception text would carry the RPC address.
        return False, "xrpld admin RPC unreachable (stopped, crashed, or OOM-killed?)"
    return evaluate(info, max_ledger_age)


def ping(ping_url, ok, reason):
    url = ping_url.rstrip("/") + ("" if ok else "/fail")
    req = urllib.request.Request(url, data=reason.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=PING_TIMEOUT):
        pass


def main():
    ping_url = os.environ.get("HC_PING_URL", "").strip()
    if not ping_url:
        print("HC_PING_URL not set", file=sys.stderr)
        return 2
    admin_rpc = os.environ.get("XRPLD_ADMIN_RPC", "127.0.0.1:5006")
    max_age = int(os.environ.get("HC_MAX_LEDGER_AGE", DEFAULT_MAX_LEDGER_AGE))

    ok, reason = check(admin_rpc, max_age)
    print(("OK: " if ok else "FAIL: ") + reason)
    try:
        ping(ping_url, ok, reason)
    except (urllib.error.URLError, OSError) as exc:
        # Expected during a WAN outage -- the missing ping IS the alert.
        print(f"ping not delivered: {exc.__class__.__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
