# XRPL Validator Node Tooling

Terminal dashboard and JSON metrics endpoint for an XRPL validator node running on Ubuntu with xrpld (the renamed `rippled` package, 3.2.0+).

On every SSH login you get a live dashboard showing validator state, system resources, amendment votes, and network info. The same data is served as JSON at `http://127.0.0.1:8080/metrics` for use by external dashboards or monitoring tools.

> **Amendment voting CLI:** The `amend` interactive TUI is in progress on the [`amend-tui`](../../tree/amend-tui) branch.

---

## What You Get

**SSH login dashboard** (rendered to MOTD every 30s via cron):
- Validator state, ledger seq, peer count, uptime
- CPU / RAM / disk usage with progress bars, CPU temperature, CPU power draw (Intel RAPL)
- LAN + Tailscale IP, SSH session count, P2P port status
- Pending amendment list with your current vote (YES/NO) and network majority status
- Recent xrpld warnings/errors

**`GET /metrics` JSON endpoint** (port 8080, localhost):
- Same data as above in machine-readable JSON, with CORS enabled

**Web dashboard** (`frontend/validator.html`):
- Browser-based version of the dashboard, fetches from your Tailscale Funnel URL every 5s
- Graceful offline handling with last-seen timestamp
- Host on GitHub Pages or any static host
- ⚠ **Mirror required:** the author's live page (joshuahamsa.com/validator.html) is served
  from the separate `joshuahamsa/joshuahamsa.github.io` repo, which keeps its own copy of
  this file. Changes here do not reach it — apply them in both places. See the comment at
  the top of `frontend/validator.html`.

---

## Prerequisites

- Ubuntu 22.04+ (or similar Debian-based distro)
- [`xrpld`](https://xrpl.org/docs/infrastructure/installation) installed and synced, admin RPC on `127.0.0.1:5006` (legacy `rippled` installs also work — point the `XRPLD_*` keys in `config/validator.conf` at the old binary/unit/cfg; see `config/validator.conf.example`)
- Python 3.10+
- `sensors` (lm-sensors) for CPU temperature: `sudo apt install lm-sensors`
- Intel CPU with RAPL support for power metrics (optional — skipped gracefully if absent)
- [Tailscale](https://tailscale.com/download/linux) installed if you want the metrics endpoint accessible over the internet via Funnel

---

## Installation

Clone the repo and run the setup wizard. The wizard handles all configuration and installs all components.

```bash
git clone https://github.com/joshuahamsa/validator-node.git
cd validator-node
bash motd/setup.sh
```

`setup.sh` prompts for:
- Your Linux username and home directory
- Path to your validator key JSON directory (usually `~/.ripple`)
- Your validator domain
- Your Tailscale Funnel URL (optional — can configure later)

It writes `config/validator.conf`, installs it to `/etc/validator-node/validator.conf`, and optionally runs all install scripts for you.

### Manual installation (advanced)

If you prefer to install components individually:

1. Copy and fill in the config template:
   ```bash
   cp config/validator.conf.example config/validator.conf
   # Edit config/validator.conf with your values
   sudo mkdir -p /etc/validator-node
   sudo cp config/validator.conf /etc/validator-node/validator.conf
   ```

2. Install the metrics server:
   ```bash
   sudo bash motd/install-service.sh
   ```

3. Install RAPL power reader (Intel CPUs, optional):
   ```bash
   sudo bash motd/install-rapl.sh
   ```

4. Install the MOTD cron and dashboard hook:
   ```bash
   sudo cp motd/motd-validator-render /usr/local/bin/motd-validator-render
   sudo chmod 755 /usr/local/bin/motd-validator-render
   sudo bash motd/cron-install.sh
   ```

---

## Tailscale Funnel (required for remote access)

The metrics server binds to `127.0.0.1:8080` — localhost only. To access the JSON endpoint from outside the machine (e.g. from a browser-based dashboard or another device on your tailnet), use **Tailscale Funnel**:

```bash
tailscale funnel 8080
```

This exposes `https://<your-hostname>.ts.net/metrics` publicly over HTTPS. The endpoint has CORS enabled so it can be consumed directly from a browser.

To make Funnel persistent across reboots:

```bash
tailscale funnel --bg 8080
```

To check or remove it:

```bash
tailscale funnel status
tailscale funnel reset
```

> **Note:** Tailscale Funnel requires a Tailscale account with Funnel enabled. See [Tailscale Funnel docs](https://tailscale.com/kb/1223/funnel).

---

## Verifying the Endpoint

```bash
curl -s http://127.0.0.1:8080/metrics | python3 -m json.tool | grep -E '"state"|"ledger_seq"|"amendments"'
```

Check amendment votes directly against xrpld:

```bash
sudo xrpld --rpc_ip=127.0.0.1:5006 feature \
  | jq '.result.features
    | to_entries
    | map(select(.value.enabled == false and .value.vetoed != "Obsolete"))
    | from_entries'
```

---

## Service Management

```bash
sudo systemctl status metrics-server
sudo systemctl restart metrics-server
sudo journalctl -u metrics-server -n 50 --no-pager
```

---

## File Overview

```
motd/
├── metrics_server.py       # HTTP server → GET /metrics (JSON)
├── motd-validator-render   # Bash script → renders ANSI dashboard to /var/cache/motd-validator
├── install-service.sh      # Deploy metrics-server systemd unit + sudoers
├── install-rapl.sh         # Deploy RAPL CPU power reader
└── cron-install.sh         # Deploy cron job + MOTD hook

frontend/
├── validator.html          # Browser dashboard — reads METRICS_URL from config.js
├── config.js               # (git-ignored) written by motd/setup.sh: window.METRICS_URL = '…'
└── styles.css              # Shared stylesheet
```
