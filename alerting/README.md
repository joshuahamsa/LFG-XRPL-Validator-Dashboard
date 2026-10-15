# Off-host outage alerting

The validator can't report its own WAN outage: when the link is down, nothing it
sends gets out. So this is a dead-man's switch. The box checks in every minute,
and [Healthchecks.io](https://healthchecks.io) raises the alarm when check-ins
stop or report a failure.

```
 validator (every 60s)            healthchecks.io               you
 ┌──────────────────┐  ping      ┌─────────────────┐  email    ┌─────────────┐
 │ healthcheck.py   │ ─────────▶ │ silent > grace? │ ────────▶ │ inbox       │
 │ admin RPC :5006  │ /fail+why  │ or /fail?       │  webhook  │ GitHub issue│
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

### 3. GitHub issue tracking (webhook → `repository_dispatch`)

`.github/workflows/outage-tracker.yml` opens an `outage` issue on down and
comments + closes it on recovery. Healthchecks.io triggers it via the GitHub API.

1. Create a **fine-grained PAT**: only this repository, permission
   **Contents: Read and write** (required by the dispatch endpoint), nothing else.
   It lives only in Healthchecks.io.
2. In Healthchecks.io: Integrations → **Webhook**, then attach it to the check.

   | | Execute when check goes **down** | Execute when check goes **up** |
   |---|---|---|
   | Method | `POST` | `POST` |
   | URL | `https://api.github.com/repos/joshuahamsa/LFG-XRPL-Validator-Dashboard/dispatches` | same |
   | Body | see below | see below |
   | Headers | see below | same |

   Down body:
   ```json
   {"event_type": "validator-down", "client_payload": {"check": $NAME_JSON, "at": "$NOW", "reason": $BODY_JSON}}
   ```
   Up body:
   ```json
   {"event_type": "validator-up", "client_payload": {"check": $NAME_JSON, "at": "$NOW"}}
   ```
   Headers (both):
   ```
   Authorization: Bearer <PAT>
   Accept: application/vnd.github+json
   X-GitHub-Api-Version: 2022-11-28
   ```
   `$BODY_JSON` is the last ping's body, i.e. the `/fail` reason. For a silent
   outage (WAN down) it is empty and the workflow fills in "No check-ins received".

**This repo is public, so outage issues are public.** `healthcheck.py` keeps
reasons generic (no IPs, hostnames, or keys) for that reason.

## Testing

```bash
python3 -m unittest -v alerting/test_healthcheck.py
```

End to end: use Healthchecks.io's **Send test notification** on the webhook,
or temporarily point `XRPLD_ADMIN_RPC` at a dead port in the service and run
`sudo systemctl start validator-healthcheck`.
