#!/bin/bash
set -e

echo "=== C2C Order Grabber Bot - Initial Setup ==="

# Update system
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y

# Install dependencies
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    jq

# Create app user
useradd -m -s /bin/bash c2cbot || true

# Clone repository
cd /home/c2cbot
if [ ! -d "c2c-order-grabber" ]; then
    sudo -u c2cbot git clone ${github_repo} c2c-order-grabber
fi

cd c2c-order-grabber
sudo -u c2cbot git checkout ${github_branch}
sudo -u c2cbot git pull

# Setup Python virtual environment
sudo -u c2cbot python3 -m venv venv
sudo -u c2cbot venv/bin/pip install --upgrade pip
sudo -u c2cbot venv/bin/pip install -r requirements.txt

# Create .env file with secrets from Terraform
cat > /home/c2cbot/c2c-order-grabber/.env << 'EOF'
# Auto-generated from Terraform variables
TELEGRAM_BOT_TOKEN=${telegram_bot_token}
ADMIN_CHAT_ID=${admin_chat_id}
INVITE_CODE=${invite_code}

# AWS Cognito (public config)
AWS_REGION=us-east-1
COGNITO_CLIENT_ID=6eio0hlq4tmr2o9d30ht9cvfn7
COGNITO_USER_POOL_ID=us-east-1_9szPtqd8w
COGNITO_IDENTITY_POOL_ID=us-east-1:db254d71-fe90-4631-bee5-d7ed0a489588

# Optional proxy settings
HTTP_PROXY=${http_proxy}
HTTPS_PROXY=${https_proxy}

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
LOG_FILE=bot.log
EOF

chown c2cbot:c2cbot /home/c2cbot/c2c-order-grabber/.env
chmod 600 /home/c2cbot/c2c-order-grabber/.env

# Create data directory
sudo -u c2cbot mkdir -p /home/c2cbot/c2c-order-grabber/data

# Setup systemd service
cat > /etc/systemd/system/c2c-bot.service << 'SYSTEMD_EOF'
[Unit]
Description=C2C Order Grabber Telegram Bot
After=network.target

[Service]
Type=simple
User=c2cbot
WorkingDirectory=/home/c2cbot/c2c-order-grabber
Environment="PATH=/home/c2cbot/c2c-order-grabber/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/c2cbot/c2c-order-grabber/.env
ExecStart=/home/c2cbot/c2c-order-grabber/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

# Enable and start service
systemctl daemon-reload
systemctl enable c2c-bot.service
systemctl start c2c-bot.service

echo "=== Setup completed! Bot is running ==="
systemctl status c2c-bot.service --no-pager
