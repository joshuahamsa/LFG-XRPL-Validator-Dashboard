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
DEFAULT_FAIL_AFTER = 3  # consecutive failed checks (1/min) before /fail
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


def _streak_path():
    # systemd's StateDirectory= sets STATE_DIRECTORY (writable by User=).
    state_dir = os.environ.get("STATE_DIRECTORY", "").split(":")[0]
    return os.path.join(state_dir, "fail_streak") if state_dir else None


def debounce(ok, reason, fail_after, path):
    """Return (send_fail, reason) after updating the consecutive-failure streak.

    Short sync blips (a ledger 30-60 s stale, a minute of `syncing`) recover
    by themselves and used to page on every occurrence. A /fail is now sent
    only once `fail_after` consecutive checks have failed. Earlier failures go
    out as a success ping whose body says "transient", so they still appear
    in the Healthchecks.io event log. With no usable state file it falls back
    to alerting immediately: losing the debounce is better than losing alerts.
    """
    if fail_after <= 1 or path is None:
        return (not ok), reason
    try:
        with open(path) as f:
            streak = int(f.read().strip() or 0)
    except (OSError, ValueError):
        streak = 0
    streak = 0 if ok else streak + 1
    try:
        with open(path, "w") as f:
            f.write(str(streak))
    except OSError:
        return (not ok), reason
    if ok:
        return False, reason
    if streak >= fail_after:
        return True, f"{reason} [{streak} consecutive checks]"
    return False, f"transient ({streak}/{fail_after}): {reason}"


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

    fail_after = int(os.environ.get("HC_FAIL_AFTER", DEFAULT_FAIL_AFTER))

    ok, reason = check(admin_rpc, max_age)
    print(("OK: " if ok else "FAIL: ") + reason)
    send_fail, reason = debounce(ok, reason, fail_after, _streak_path())
    try:
        ping(ping_url, not send_fail, reason)
    except (urllib.error.URLError, OSError) as exc:
        # Expected during a WAN outage -- the missing ping IS the alert.
        print(f"ping not delivered: {exc.__class__.__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
