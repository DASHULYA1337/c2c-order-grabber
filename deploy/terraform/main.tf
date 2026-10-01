terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Lightsail Instance
resource "aws_lightsail_instance" "c2c_bot" {
  name              = var.instance_name
  availability_zone = "${var.aws_region}a"
  blueprint_id      = "ubuntu_22_04"
  bundle_id         = var.bundle_id

  key_pair_name = aws_lightsail_key_pair.c2c_bot.name

  user_data = templatefile("${path.module}/user_data.sh", {
    github_repo        = var.github_repo
    github_branch      = var.github_branch
    telegram_bot_token = var.telegram_bot_token
    admin_chat_id      = var.admin_chat_id
    invite_code        = var.invite_code
    http_proxy         = var.http_proxy
    https_proxy        = var.https_proxy
  })

  tags = {
    Project     = "c2c-order-grabber"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Static IP
resource "aws_lightsail_static_ip" "c2c_bot" {
  name = "${var.instance_name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "c2c_bot" {
  static_ip_name = aws_lightsail_static_ip.c2c_bot.name
  instance_name  = aws_lightsail_instance.c2c_bot.name
}

# SSH Key Pair
resource "aws_lightsail_key_pair" "c2c_bot" {
  name = "${var.instance_name}-key"
}

# Firewall rules
resource "aws_lightsail_instance_public_ports" "c2c_bot" {
  instance_name = aws_lightsail_instance.c2c_bot.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_ips
  }
}
