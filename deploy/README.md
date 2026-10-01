# Deployment

AWS Lightsail deployment with Terraform and GitHub Actions CI/CD.

## Architecture

```
GitHub (main) → GitHub Actions → Terraform → AWS Lightsail
                                          ↓ (secrets via user_data)
```

## Setup

### 1. AWS Credentials

```bash
aws configure
# Enter Access Key ID and Secret Access Key
```

### 2. GitHub Secrets

Add in `Settings` → `Secrets and variables` → `Actions`:

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID
INVITE_CODE (optional)
```

### 3. Setup Terraform Remote State (optional but recommended)

```bash
# Create S3 bucket for state
aws s3api create-bucket \
  --bucket c2c-bot-terraform-state-1 \
  --region eu-north-1 \
  --create-bucket-configuration LocationConstraint=eu-north-1

aws s3api put-bucket-versioning \
  --bucket c2c-bot-terraform-state-1 \
  --versioning-configuration Status=Enabled \
  --region eu-north-1

aws s3api put-bucket-encryption \
  --bucket c2c-bot-terraform-state-1 \
  --region eu-north-1 \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Create DynamoDB table for state locking
aws dynamodb create-table \
  --table-name c2c-bot-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region eu-north-1

# Uncomment backend config in deploy/terraform/backend.tf
# Then migrate state: terraform init -migrate-state
```

### 4. Deploy Infrastructure

```bash
cd deploy/terraform
terraform init
terraform apply

# Save outputs
terraform output static_ip
terraform output -raw private_key > ../../c2c-order-grabber-key.pem
chmod 600 ../../c2c-order-grabber-key.pem
```

## Usage

### Auto-deploy

Push to `main` triggers automatic deployment:

```bash
git push origin main
```

### SSH Access

```bash
ssh -i c2c-order-grabber-key.pem ubuntu@YOUR_IP

# View logs
sudo journalctl -u c2c-bot.service -f

# Restart bot
sudo systemctl restart c2c-bot.service
```

### Update Environment Variables

```bash
# Update via AWS CLI
aws ssm put-parameter \
  --name "/c2c-bot/TELEGRAM_BOT_TOKEN" \
  --value "new_token" \
  --type "SecureString" \
  --overwrite

# Restart bot
ssh -i c2c-order-grabber-key.pem ubuntu@YOUR_IP
sudo systemctl restart c2c-bot.service
```

## Structure

```
deploy/
├── terraform/
│   ├── main.tf          # Infrastructure
│   ├── variables.tf     # Config
│   ├── outputs.tf       # Outputs (IP, SSH key)
│   ├── backend.tf       # Remote state config (S3)
│   └── user_data.sh     # Server init
└── scripts/             # Personal scripts (gitignored)
```

## Troubleshooting

```bash
# Check instance
aws lightsail get-instance --instance-name c2c-order-grabber

# View logs
ssh -i c2c-order-grabber-key.pem ubuntu@YOUR_IP \
  'sudo journalctl -u c2c-bot.service -n 50'

# Verify .env
ssh -i c2c-order-grabber-key.pem ubuntu@YOUR_IP \
  'cat /home/c2cbot/c2c-order-grabber/.env'
```

## Destroy

```bash
cd deploy/terraform
terraform destroy
```
