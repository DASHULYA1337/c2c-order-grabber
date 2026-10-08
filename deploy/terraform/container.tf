resource "aws_lightsail_container_service" "c2c_bot" {
  name  = var.instance_name
  power = var.container_power
  scale = var.container_scale

  tags = {
    Project     = "c2c-order-grabber"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_lightsail_container_service_deployment_version" "c2c_bot" {
  container {
    container_name = "c2c-bot"
    image = var.docker_registry_username != "" ? "${var.docker_registry_username}/${var.docker_image_name}:${var.docker_image_tag}" : "${var.docker_image_name}:${var.docker_image_tag}"

    environment = {
      TELEGRAM_BOT_TOKEN        = var.telegram_bot_token
      ADMIN_CHAT_ID             = var.admin_chat_id
      INVITE_CODE               = var.invite_code
      AWS_REGION                = "us-east-1"
      COGNITO_CLIENT_ID         = "6eio0hlq4tmr2o9d30ht9cvfn7"
      COGNITO_USER_POOL_ID      = "us-east-1_9szPtqd8w"
      COGNITO_IDENTITY_POOL_ID  = "us-east-1:db254d71-fe90-4631-bee5-d7ed0a489588"
      HTTP_PROXY                = var.http_proxy
      HTTPS_PROXY               = var.https_proxy
      DATABASE_URL              = "sqlite+aiosqlite:///./data/bot.db"
      LOG_FILE                  = "bot.log"
    }
  }

  service_name = aws_lightsail_container_service.c2c_bot.name
}
