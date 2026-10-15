# Off-host outage alerting

The validator can't report its own WAN outage: when the link is down, nothing it
sends gets out. So this is a dead-man's switch. The box checks in every minute,
and [Healthchecks.io](https://healthchecks.io) raises the alarm when check-ins
stop or report a failure.

```
 validator (every 60s)            healthchecks.io               you
 ┌──────────────────┐  ping      ┌─────────────────┐  email    ┌─────────────┐
 │ healthcheck.py   │ ─────────▶ │ silent > grace? │ ────────▶ │ inbox       │
 │ admin RPC :5006  │ /fail+why  │ or /fail?       │  GitHub   │ GitHub issue│
 └──────────────────┘            └─────────────────┘ ────────▶ │ (auto-close)│
                                                                └─────────────┘
```

| Failure | What Healthchecks.io sees | Alert |
|---|---|---|
| WAN / router / ISP down | pings stop | after the grace period |
| Host down (power, kernel, reboot loop) | pings stop | after the grace period |
| xrpld stopped / crashed / OOM-killed | `/fail` "admin RPC unreachable" | immediate |
| xrpld up but not `proposing`, or validated ledger > 30 s old | `/fail` with the state | immediate |
| Amendment blocked | `/fail` "amendment blocked" | immediate |

The check must use the **admin** RPC. The public port reports `full` for a
healthy validator and hides `pubkey_validator`.

## Setup

### 1. Healthchecks.io check

New check → **Simple**, period **1 minute**, grace **5 minutes**. Copy the ping
URL (`https://hc-ping.com/<uuid>`).

Email is on by default for the account owner.

### 2. Install on the validator

```bash
sudo bash alerting/install.sh   # prompts for the ping URL once
```

The URL is stored in `/etc/validator-node/healthcheck.env` (mode 600). Treat it
as a credential, since anyone holding it can send fake check-ins. Logs:
`journalctl -u validator-healthcheck`.

### 3. GitHub issue tracking

Opening and closing are handled by two different pieces:

- **Opening:** Healthchecks.io's native **GitHub** integration (Integrations →
  GitHub, installed as a GitHub App on this repo only, so no personal token).
  Set its label to **`outage`**. It opens a "<check> is DOWN" issue on every
  down event, with the last ping's body (the `/fail` reason) included. It never
  closes issues.
- **Closing:** `.github/workflows/outage-tracker.yml` runs every 15 minutes
  (and on demand from the Actions tab). When an `outage` issue is open, it
  reads the check's flip history from the Healthchecks.io API. For each issue
  it finds the down-flip it was opened for and the next up-flip, then comments
  the exact times + duration and closes it. With no open issues it doesn't
  call Healthchecks.io at all.

Repo secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `HC_API_KEY_READONLY` | Healthchecks.io → project Settings → API Access → **read-only** key. It can't change checks or send pings. |
| `HC_CHECK_ID` | The check's UUID (the part after `hc-ping.com/`). Stored as a secret because it doubles as the ping URL. |

GitHub disables scheduled workflows on public repos after **60 days without
commits**. If issues stop auto-closing, re-enable the workflow in the Actions tab.

**This repo is public, so outage issues are public.** `healthcheck.py` keeps
reasons generic (no IPs, hostnames, or keys) for that reason.

## Testing

```bash
python3 -m unittest -v alerting/test_healthcheck.py
```

End to end: use **Send test notification** on the GitHub integration (opens a test issue),
or temporarily point `XRPLD_ADMIN_RPC` at a dead port in the service and run
`sudo systemctl start validator-healthcheck`.
