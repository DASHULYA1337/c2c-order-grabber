# C2C Order Grabber Bot

Telegram bot for automatic monitoring and grabbing orders on Cards2Cards platform with AWS Cognito authentication.

> Fork of the original [Ps1nu5/c2c-order-grabber](https://github.com/Ps1nu5/c2c-order-grabber) with enhancements and automated AWS Lightsail deployment.

## Features

- Real-time order monitoring
- Configurable amount filters (min/max)
- Automatic AWS Cognito authentication
- Proxy support to bypass IP blocks
- SQLite database for settings and logs
- CloudFront WAF bypass using curl_cffi
- Notifications for grabbed and missed orders

## Requirements

- Python 3.10+
- Telegram Bot Token (get from [@BotFather](https://t.me/botfather))
- Cards2Cards credentials

## Local Installation

### 1. Clone repository

```bash
git clone https://github.com/DASHULYA1337/c2c-order-grabber.git
cd c2c-order-grabber
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_CHAT_ID=your_telegram_chat_id_here

# Optional: invite code for access control
INVITE_CODE=your_secret_invite_code

# AWS Cognito (can keep as-is)
AWS_REGION=us-east-1
COGNITO_CLIENT_ID=6eio0hlq4tmr2o9d30ht9cvfn7
COGNITO_USER_POOL_ID=us-east-1_9szPtqd8w
COGNITO_IDENTITY_POOL_ID=us-east-1:db254d71-fe90-4631-bee5-d7ed0a489588
```

### 5. Run bot

```bash
python main.py
```

## Usage

1. Start bot with `/start` command in Telegram
2. Enter invite code (if configured)
3. Enter your Cards2Cards credentials
4. Configure amount filters (optional)
5. Start monitoring

### Bot Commands

- `/start` - Start bot / authenticate
- `/stop` - Stop monitoring
- `/settings` - Configure filters
- `/status` - View statistics

## Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token | - |
| `ADMIN_CHAT_ID` | Yes | Admin chat ID | - |
| `INVITE_CODE` | No | Invite code for access control | - |
| `AWS_REGION` | No | AWS region | `us-east-1` |
| `DATABASE_URL` | No | Database URL | `sqlite+aiosqlite:///./data/bot.db` |
| `LOG_FILE` | No | Log file path | `bot.log` |
| `POLL_INTERVAL_S` | No | Poll interval (seconds) | `0.5` |
| `DEBUG` | No | Debug mode | `false` |
| `HTTP_PROXY` | No | HTTP proxy | - |
| `HTTPS_PROXY` | No | HTTPS proxy | - |

### Proxy Configuration

To bypass IP blocks, configure proxy:

```env
HTTP_PROXY=http://proxy.example.com:8080
HTTPS_PROXY=http://proxy.example.com:8080
# SOCKS5 proxies are also supported
```

## Project Structure

```
c2c-order-grabber/
├── main.py              # Entry point
├── app.py               # Main application class
├── config.py            # Configuration
├── cognito_auth.py      # AWS Cognito authentication
├── api_client.py        # Cards2Cards API client
├── aws_signer.py        # AWS Signature V4
├── user_session.py      # User session management
├── monitor.py           # Order monitoring
├── processor.py         # Order processing
├── bot/                 # Telegram bot
│   ├── handlers/        # Command handlers
│   └── keyboards.py     # Keyboards
├── db/                  # Database
│   ├── engine.py        # SQLAlchemy engine
│   ├── models.py        # Data models
│   └── repository.py    # Repositories
├── deploy/              # Deployment
│   ├── terraform/       # Infrastructure as Code
│   └── scripts/         # Deployment scripts
├── data/                # Data (DB, logs)
└── requirements.txt     # Dependencies
```

## AWS Lightsail Deployment

Automated deployment with Terraform and GitHub Actions. Full documentation: [deploy/README.md](deploy/README.md)

### Quick Start

```bash
# 1. Deploy infrastructure
cd deploy/terraform
terraform init
terraform apply

# 2. Auto-deploy on push to main
git push origin main
```


### Management

```bash
# SSH connection
ssh -i c2c-order-grabber-key.pem ubuntu@YOUR_IP

# View logs
sudo journalctl -u c2c-bot.service -f
```

## Docker (Alternative)

### Build image

```bash
docker build -t c2c-order-grabber .
```

### Run container

```bash
docker-compose up -d
```

## Security

- Never commit `.env` file to git
- Use strong invite codes
- Store private keys securely
- Update dependencies regularly

## Technologies

- [aiogram](https://github.com/aiogram/aiogram) - Telegram Bot Framework
- [aiohttp](https://github.com/aio-libs/aiohttp) - Async HTTP client
- [SQLAlchemy](https://www.sqlalchemy.org/) - ORM
- [curl_cffi](https://github.com/yifeikong/curl_cffi) - CloudFront WAF bypass

## License

Private project

## Authors

- Original project: [@Ps1nu5](https://github.com/Ps1nu5)
- Fork and enhancements: [@DASHULYA1337](https://github.com/DASHULYA1337)
