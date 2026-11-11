#!/usr/bin/env python3
"""UPS power alerting via NUT + Healthchecks.io.

Run every minute by ups-healthcheck.timer. Reads the UPS through NUT's `upsc`
and pings a *separate* Healthchecks.io check (UPS_HC_PING_URL):

  on mains, battery fine -> GET  $UPS_HC_PING_URL        (check stays/returns up)
  on battery / low / bad -> POST $UPS_HC_PING_URL/fail   (alerts immediately)

Healthchecks.io only notifies on state changes, so a long outage sends one
"down" email and one "up" email when mains power returns, not one per minute.
If the power cut also takes out the router, pings stop and the check alerts
after its grace period instead.

Reasons stay generic (no hostnames/IPs), matching healthcheck.py.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from healthcheck import ping  # noqa: E402

UPSC_TIMEOUT = 10


def parse_upsc(text):
    """Parse `upsc <ups>` output ("key: value" lines) into a dict."""
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key and " " not in key.strip():
            out[key.strip()] = value.strip()
    return out


def _summary(data):
    parts = []
    if data.get("battery.charge"):
        parts.append(f"battery {data['battery.charge']}%")
    runtime = data.get("battery.runtime", "")
    if runtime.isdigit():
        parts.append(f"~{int(runtime) // 60} min runtime")
    if data.get("ups.load"):
        parts.append(f"load {data['ups.load']}%")
    return ", ".join(parts)


def evaluate(data):
    """Return (ok, reason) for parsed upsc data."""
    status = data.get("ups.status", "").split()
    if not status:
        return False, "UPS status unavailable (USB unplugged or NUT driver down?)"
    summary = _summary(data)
    tail = f" ({summary})" if summary else ""
    if "LB" in status:
        return False, f"UPS on battery and LOW, host shutdown imminent{tail}"
    if "OB" in status:
        return False, f"UPS on battery, mains power lost{tail}"
    if "RB" in status:
        return False, f"UPS reports battery needs replacing{tail}"
    if "OVER" in status:
        return False, f"UPS overloaded{tail}"
    if "OL" in status:
        return True, f"on mains{tail}"
    return False, f"UPS status {' '.join(status)}{tail}"


def read_ups(ups_name):
    """Return parsed upsc data, or {} if NUT can't be reached."""
    try:
        res = subprocess.run(
            ["upsc", ups_name],
            capture_output=True,
            text=True,
            timeout=UPSC_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if res.returncode != 0:
        return {}
    return parse_upsc(res.stdout)


def main():
    ping_url = os.environ.get("UPS_HC_PING_URL", "").strip()
    if not ping_url:
        print("UPS_HC_PING_URL not set", file=sys.stderr)
        return 2
    ups_name = os.environ.get("UPS_NAME", "apc@localhost")

    ok, reason = evaluate(read_ups(ups_name))
    print(("OK: " if ok else "FAIL: ") + reason)
    try:
        ping(ping_url, ok, reason)
    except OSError as exc:  # URLError is an OSError
        print(f"ping not delivered: {exc.__class__.__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
