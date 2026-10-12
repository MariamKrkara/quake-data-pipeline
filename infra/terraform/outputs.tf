output "public_ip" {
  description = "Public IP of the pipeline server"
  value       = aws_instance.pipeline.public_ip
}

output "ssh_command" {
  description = "Command to log in to the server"
  value       = "ssh ubuntu@${aws_instance.pipeline.public_ip}"
}
