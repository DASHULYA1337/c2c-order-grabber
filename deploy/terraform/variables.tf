variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "eu-north-1"
}

variable "instance_name" {
  description = "Lightsail instance name"
  type        = string
  default     = "c2c-order-grabber"
}

variable "bundle_id" {
  description = "Lightsail bundle ID (instance size)"
  type        = string
  default     = "nano_3_0"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "github_repo" {
  description = "GitHub repository URL"
  type        = string
  default     = "https://github.com/DASHULYA1337/c2c-order-grabber.git"
}

variable "github_branch" {
  description = "GitHub branch to deploy"
  type        = string
  default     = "main"
}

variable "ssh_allowed_ips" {
  description = "List of IPs allowed to SSH"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# Secret variables (passed via GitHub Secrets or terraform.tfvars)
variable "telegram_bot_token" {
  description = "Telegram Bot Token"
  type        = string
  sensitive   = true
}

variable "admin_chat_id" {
  description = "Admin Telegram Chat ID"
  type        = string
}

variable "invite_code" {
  description = "Invite code for bot access"
  type        = string
  sensitive   = true
  default     = ""
}

variable "http_proxy" {
  description = "HTTP Proxy URL (optional)"
  type        = string
  default     = ""
}

variable "https_proxy" {
  description = "HTTPS Proxy URL (optional)"
  type        = string
  default     = ""
}
