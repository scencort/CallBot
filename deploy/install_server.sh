#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/call_bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="call_bot"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo bash deploy/install_server.sh"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python interpreter not found: ${PYTHON_BIN}"
  exit 1
fi

mkdir -p "${APP_DIR}"

cp bot.py "${APP_DIR}/bot.py"
cp requirements.txt "${APP_DIR}/requirements.txt"

if [[ -f .env.example ]]; then
  cp .env.example "${APP_DIR}/.env.example"
fi

if [[ -f calls_history.jsonl && ! -f "${APP_DIR}/calls_history.jsonl" ]]; then
  cp calls_history.jsonl "${APP_DIR}/calls_history.jsonl"
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp .env.example "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from .env.example"
fi

if [[ ! -d "${APP_DIR}/.venv" ]]; then
  "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
fi

"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --upgrade -r "${APP_DIR}/requirements.txt"

cp deploy/call_bot.service "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo
echo "Installation completed."
echo "1. Edit ${APP_DIR}/.env and set TELEGRAM_BOT_TOKEN"
echo "2. Start service: systemctl start ${SERVICE_NAME}"
echo "3. Check logs: journalctl -u ${SERVICE_NAME} -f"
