# Terraform state backend configuration
# Uncomment after creating S3 bucket and DynamoDB table

terraform {
  backend "s3" {
    bucket         = "c2c-bot-terraform-state-1"
    key            = "lightsail/terraform.tfstate"
    region         = "eu-north-1"
    encrypt        = true
    dynamodb_table = "c2c-bot-terraform-locks"
  }
}

