# Deployment

AWS Lightsail Container Service deployment with Terraform and GitHub Actions CI/CD.

## Architecture

```
GitHub (main) → GitHub Actions → Docker Hub → AWS Lightsail Container Service
                 ├─ terraform.yml: manages infrastructure (container service)
                 └─ build-and-deploy.yml: builds & deploys containers
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
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
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
```

### 4. Deploy Infrastructure

```bash
cd deploy/terraform
terraform init
terraform apply \
  -var="telegram_bot_token=$TELEGRAM_BOT_TOKEN" \
  -var="admin_chat_id=$ADMIN_CHAT_ID" \
  -var="docker_registry_username=$DOCKERHUB_USERNAME"

terraform output
```

## Usage

### Auto-deploy

Push to `main` triggers automatic container build and deployment:

```bash
git push origin main
```

### View Logs

```bash
aws lightsail get-container-log \
  --service-name c2c-order-grabber \
  --container-name c2c-bot \
  --region eu-north-1 \
  --output text
```

### Update Environment Variables

Edit `deploy/terraform/container.tf` → update `environment` block → run `terraform apply`.

## Structure

```
deploy/
├── terraform/
│   ├── main.tf          # Terraform provider config
│   ├── container.tf     # Container Service & deployment
│   ├── variables.tf     # Variables
│   ├── outputs.tf       # Outputs (service URL, status)
│   ├── backend.tf       # Remote state config (S3)
│   └── user_data.sh     # OLD (deprecated, not used)
└── .github/workflows/
    ├── terraform.yml         # Infrastructure deployment
    └── build-and-deploy.yml  # Container build & deploy
```

## Troubleshooting

```bash
# Check container service status
aws lightsail get-container-services \
  --service-name c2c-order-grabber \
  --region eu-north-1

# View container logs
aws lightsail get-container-log \
  --service-name c2c-order-grabber \
  --container-name c2c-bot \
  --region eu-north-1

# Check deployments
aws lightsail get-container-service-deployments \
  --service-name c2c-order-grabber \
  --region eu-north-1
```

## Destroy

```bash
cd deploy/terraform
terraform destroy
```
