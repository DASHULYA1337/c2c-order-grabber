output "instance_id" {
  description = "Lightsail instance ID"
  value       = aws_lightsail_instance.c2c_bot.id
}

output "instance_name" {
  description = "Lightsail instance name"
  value       = aws_lightsail_instance.c2c_bot.name
}

output "static_ip" {
  description = "Static IP address"
  value       = aws_lightsail_static_ip.c2c_bot.ip_address
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh -i ${aws_lightsail_key_pair.c2c_bot.name}.pem ubuntu@${aws_lightsail_static_ip.c2c_bot.ip_address}"
}

output "private_key" {
  description = "Private SSH key (save to file)"
  value       = aws_lightsail_key_pair.c2c_bot.private_key
  sensitive   = true
}
