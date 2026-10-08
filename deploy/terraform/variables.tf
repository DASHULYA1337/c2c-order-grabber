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
  description = "Lightsail bundle ID"
  type        = string
  default     = "small_3_0"
}

variable "container_power" {
  description = "Container service power"
  type        = string
  default     = "micro"
}

variable "container_scale" {
  description = "Number of container instances"
  type        = number
  default     = 1
}

variable "docker_registry_username" {
  description = "Docker registry username (e.g., Docker Hub username)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "docker_image_name" {
  description = "Docker image name (without username/registry)"
  type        = string
  default     = "c2c-order-grabber"
}

variable "docker_image_tag" {
  description = "Docker image tag"
  type        = string
  default     = "latest"
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
