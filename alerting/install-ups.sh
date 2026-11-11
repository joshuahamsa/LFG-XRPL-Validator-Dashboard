#!/usr/bin/env bash
# Deploy the UPS power check (systemd service + 1-minute timer).
# Run as: sudo bash install-ups.sh
# Requires NUT already serving the UPS (`upsc <name>` works) and
# /etc/validator-node/validator.conf (run motd/setup.sh first).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run with sudo: sudo bash $0"
    exit 1
fi

SYSTEM_CONFIG="/etc/validator-node/validator.conf"
if [[ ! -f "$SYSTEM_CONFIG" ]]; then
    echo "ERROR: $SYSTEM_CONFIG not found. Run motd/setup.sh first."
    exit 1
fi
# shellcheck source=/dev/null
source "$SYSTEM_CONFIG"

command -v upsc >/dev/null || { echo "ERROR: upsc not found. Install and configure NUT first."; exit 1; }

UPS_ENV="/etc/validator-node/ups-healthcheck.env"
if [[ ! -f "$UPS_ENV" ]]; then
    echo "=== Creating $UPS_ENV ==="
    default_ups="$(upsc -l 2>/dev/null | head -1)"
    default_ups="${default_ups:+${default_ups}@localhost}"
    read -rp "NUT UPS name [${default_ups:-apc@localhost}]: " ups
    ups="${ups:-${default_ups:-apc@localhost}}"
    upsc "$ups" ups.status >/dev/null 2>&1 || { echo "ERROR: 'upsc $ups' failed"; exit 1; }
    read -rp "Healthchecks.io ping URL for the UPS check (https://hc-ping.com/<uuid>): " url
    [[ "$url" == https://* ]] || { echo "ERROR: expected an https:// URL"; exit 1; }
    install -m 600 -o "$VALIDATOR_USERNAME" /dev/null "$UPS_ENV"
    printf 'UPS_HC_PING_URL=%s\nUPS_NAME=%s\n' "$url" "$ups" > "$UPS_ENV"
    echo "  done."
fi

echo "=== Writing /etc/systemd/system/ups-healthcheck.service ==="
cat > /etc/systemd/system/ups-healthcheck.service <<EOF
[Unit]
Description=UPS power check ping (NUT -> Healthchecks.io)
After=network-online.target nut-server.service

[Service]
Type=oneshot
User=${VALIDATOR_USERNAME}
EnvironmentFile=${UPS_ENV}
ExecStart=/usr/bin/python3 ${REPO_PATH}/alerting/ups_check.py
TimeoutStartSec=45
EOF
echo "  done."

echo "=== Writing /etc/systemd/system/ups-healthcheck.timer ==="
cat > /etc/systemd/system/ups-healthcheck.timer <<EOF
[Unit]
Description=Ping Healthchecks.io every minute with UPS power status

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF
echo "  done."

systemctl daemon-reload
systemctl enable --now ups-healthcheck.timer
systemctl start ups-healthcheck.service
echo
journalctl -u ups-healthcheck.service -n 3 --no-pager -o cat
echo
echo "Installed. Check status with: systemctl list-timers ups-healthcheck.timer"
