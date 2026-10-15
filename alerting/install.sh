#!/usr/bin/env bash
# Deploy the off-host outage healthcheck (systemd service + 1-minute timer).
# Run as: sudo bash install.sh
# Requires /etc/validator-node/validator.conf — run motd/setup.sh first.
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

# The ping URL is a credential (anyone holding it can fake check-ins), so it
# lives in its own file readable only by the service user.
HC_ENV="/etc/validator-node/healthcheck.env"
if [[ ! -f "$HC_ENV" ]]; then
    echo "=== Creating $HC_ENV ==="
    read -rp "Healthchecks.io ping URL (https://hc-ping.com/<uuid>): " url
    [[ "$url" == https://* ]] || { echo "ERROR: expected an https:// URL"; exit 1; }
    install -m 600 -o "$VALIDATOR_USERNAME" /dev/null "$HC_ENV"
    printf 'HC_PING_URL=%s\n' "$url" > "$HC_ENV"
    echo "  done."
fi

echo "=== Writing /etc/systemd/system/validator-healthcheck.service ==="
cat > /etc/systemd/system/validator-healthcheck.service <<EOF
[Unit]
Description=XRPL validator off-host healthcheck ping
After=network-online.target ${XRPLD_UNIT:-xrpld}.service

[Service]
Type=oneshot
User=${VALIDATOR_USERNAME}
EnvironmentFile=${SYSTEM_CONFIG}
EnvironmentFile=${HC_ENV}
ExecStart=/usr/bin/python3 ${REPO_PATH}/alerting/healthcheck.py
TimeoutStartSec=45
EOF
echo "  done."

echo "=== Writing /etc/systemd/system/validator-healthcheck.timer ==="
cat > /etc/systemd/system/validator-healthcheck.timer <<EOF
[Unit]
Description=Ping Healthchecks.io every minute with validator status

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF
echo "  done."

systemctl daemon-reload
systemctl enable --now validator-healthcheck.timer
systemctl start validator-healthcheck.service
echo
journalctl -u validator-healthcheck.service -n 3 --no-pager -o cat
echo
echo "Installed. Check status with: systemctl list-timers validator-healthcheck.timer"
