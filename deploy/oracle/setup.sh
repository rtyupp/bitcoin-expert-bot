#!/usr/bin/env bash
# تثبيت بوت توصيات البيتكوين على Oracle Cloud Always Free (Ubuntu) — بوت دائم بدون نوم
set -euo pipefail

TOKEN="${1:-}"
DAILY_CHAT_ID="${DAILY_CHAT_ID:-}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
APP_DIR=/opt/bitcoin-expert-bot

if [ -z "$TOKEN" ]; then
  echo "الاستخدام: sudo bash setup.sh <BOT_TOKEN>"
  echo "اختياري: DAILY_CHAT_ID=123 DEEPSEEK_API_KEY=sk-... sudo -E bash setup.sh <BOT_TOKEN>"
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "شغّله بـ sudo"
  exit 1
fi

USER_NAME="${SUDO_USER:-ubuntu}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q git python3 python3-venv python3-pip

if [ ! -d "$APP_DIR" ]; then
  git clone https://github.com/rtyupp/bitcoin-expert-bot.git "$APP_DIR"
fi
chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  sudo -u "$USER_NAME" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$USER_NAME" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$USER_NAME" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

cat > /etc/bitcoin-expert-bot.env <<EOF
BOT_TOKEN=$TOKEN
DAILY_CHAT_ID=$DAILY_CHAT_ID
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
EOF
chmod 600 /etc/bitcoin-expert-bot.env

sed "s/^User=.*/User=$USER_NAME/" "$APP_DIR/deploy/oracle/bitcoin-expert-bot.service" \
  > /etc/systemd/system/bitcoin-expert-bot.service

systemctl daemon-reload
systemctl enable --now bitcoin-expert-bot
sleep 6
systemctl status bitcoin-expert-bot --no-pager -l | head -12
echo ""
echo "✅ انتهى — أرسل /start لبوتك في تيليجرام"
echo "📋 السجلات: journalctl -u bitcoin-expert-bot -f"
