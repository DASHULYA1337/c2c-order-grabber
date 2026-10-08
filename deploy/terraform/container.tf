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
