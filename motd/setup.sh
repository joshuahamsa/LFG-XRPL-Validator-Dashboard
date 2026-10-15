#!/usr/bin/env bash
# First-run setup wizard for the XRPL validator-node dashboard.
# Safe to re-run: shows current values and lets you override any field.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$REPO_DIR/config"
CONFIG_FILE="$CONFIG_DIR/validator.conf"
SYSTEM_CONFIG_DIR="/etc/validator-node"
SYSTEM_CONFIG="$SYSTEM_CONFIG_DIR/validator.conf"

# Load existing config if present so re-runs show current values as defaults.
[[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE" || true

_prompt() {
    local varname="$1" prompt_text="$2"
    local current="${!varname:-}"
    local val
    if [[ -n "$current" ]]; then
        read -rp "$prompt_text [$current]: " val
        val="${val:-$current}"
    else
        read -rp "$prompt_text: " val
    fi
    printf '%s' "$val"
}

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   XRPL Validator Node — Setup        ║"
echo "╚══════════════════════════════════════╝"
echo ""

VALIDATOR_USERNAME=$(_prompt VALIDATOR_USERNAME "Linux username (runs metrics-server service)" || echo "${VALIDATOR_USERNAME:-$USER}")
VALIDATOR_USERNAME="${VALIDATOR_USERNAME:-$USER}"

VALIDATOR_HOME=$(_prompt VALIDATOR_HOME "Home directory" || echo "${VALIDATOR_HOME:-$HOME}")
VALIDATOR_HOME="${VALIDATOR_HOME:-$HOME}"

# Auto-detect validator JSON dir
_detected_json_dir="${VALIDATOR_JSON_DIR:-$VALIDATOR_HOME/.ripple}"
if [[ -z "${VALIDATOR_JSON_DIR:-}" ]] && ls "$VALIDATOR_HOME/.ripple/"*.json &>/dev/null 2>&1; then
    _detected_json_dir="$VALIDATOR_HOME/.ripple"
fi
VALIDATOR_JSON_DIR=$(_prompt VALIDATOR_JSON_DIR "Validator key JSON directory (contains *.json)" || echo "$_detected_json_dir")
VALIDATOR_JSON_DIR="${VALIDATOR_JSON_DIR:-$_detected_json_dir}"

VALIDATOR_DOMAIN=$(_prompt VALIDATOR_DOMAIN "Your validator domain (e.g. mynode.example.com)" || echo "${VALIDATOR_DOMAIN:-}")

echo ""
echo "Tailscale Funnel URL is used by frontend/validator.html (via frontend/config.js)."
echo "Leave blank if not set up yet — re-run setup.sh later to set it."
METRICS_URL=$(_prompt METRICS_URL "Tailscale Funnel URL (blank to skip)" || echo "${METRICS_URL:-}")

REPO_PATH=$(_prompt REPO_PATH "Absolute path to this repo" || echo "${REPO_PATH:-$REPO_DIR}")
REPO_PATH="${REPO_PATH:-$REPO_DIR}"

# Write config/validator.conf
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<EOF
VALIDATOR_USERNAME=$VALIDATOR_USERNAME
VALIDATOR_HOME=$VALIDATOR_HOME
VALIDATOR_JSON_DIR=$VALIDATOR_JSON_DIR
VALIDATOR_DOMAIN=$VALIDATOR_DOMAIN
METRICS_URL=$METRICS_URL
REPO_PATH=$REPO_PATH
XRPL_FEATURES_SRC=${XRPL_FEATURES_SRC:-}
XRPLD_BIN=${XRPLD_BIN:-${RIPPLED_BIN:-/usr/bin/xrpld}}
XRPLD_UNIT=${XRPLD_UNIT:-${RIPPLED_UNIT:-xrpld}}
XRPLD_CFG=${XRPLD_CFG:-${RIPPLED_CFG:-/etc/xrpld/xrpld.cfg}}
XRPLD_ADMIN_RPC=${XRPLD_ADMIN_RPC:-127.0.0.1:5006}
EOF
echo ""
echo "Written: $CONFIG_FILE"

# Write the dashboard's METRICS_URL to a git-ignored config.js, never into the
# tracked validator.html (patching that left the checkout dirty and blocked
# `git pull`). JSON-encode the URL so quotes or backslashes can't break the JS.
FRONTEND_CONFIG="$REPO_DIR/frontend/config.js"
if [[ -n "$METRICS_URL" ]]; then
    printf 'window.METRICS_URL = %s;\n' \
        "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$METRICS_URL")" \
        > "$FRONTEND_CONFIG"
    echo "Wrote METRICS_URL to: $FRONTEND_CONFIG"
fi

# Install system config (requires sudo)
echo ""
read -rp "Install config to $SYSTEM_CONFIG (requires sudo)? [Y/n]: " _yn
if [[ "${_yn,,}" != "n" ]]; then
    sudo mkdir -p "$SYSTEM_CONFIG_DIR"
    sudo cp "$CONFIG_FILE" "$SYSTEM_CONFIG"
    echo "Installed: $SYSTEM_CONFIG"
fi

# Optionally run install scripts
echo ""
read -rp "Run install scripts now (metrics-server service, MOTD cron)? [Y/n]: " _yn
if [[ "${_yn,,}" != "n" ]]; then
    echo ""
    echo "--- metrics-server systemd service ---"
    sudo bash "$REPO_DIR/motd/install-service.sh"

    echo ""
    read -rp "Install RAPL CPU power reader (Intel CPUs only)? [y/N]: " _rapl
    if [[ "${_rapl,,}" == "y" ]]; then
        sudo bash "$REPO_DIR/motd/install-rapl.sh"
    fi

    echo ""
    echo "--- MOTD cron ---"
    sudo cp "$REPO_DIR/motd/motd-validator-render" /usr/local/bin/motd-validator-render
    sudo chmod 755 /usr/local/bin/motd-validator-render
    sudo bash "$REPO_DIR/motd/cron-install.sh"
fi

echo ""
echo "=== Setup complete ==="
[[ -n "$METRICS_URL" ]] || echo "Reminder: set METRICS_URL later by re-running this script."
