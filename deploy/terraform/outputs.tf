output "container_service_name" {
  description = "Lightsail Container Service name"
  value       = aws_lightsail_container_service.c2c_bot.name
}

output "container_service_url" {
  description = "Container Service URL"
  value       = aws_lightsail_container_service.c2c_bot.url
}

output "container_service_status" {
  description = "Container Service status"
  value       = aws_lightsail_container_service.c2c_bot.state
}

output "container_service_power" {
  description = "Container Service power level"
  value       = aws_lightsail_container_service.c2c_bot.power
}

output "container_service_scale" {
  description = "Number of container instances"
  value       = aws_lightsail_container_service.c2c_bot.scale
}
