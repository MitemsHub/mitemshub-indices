# ── Outputs ────────────────────────────────────────────────────
output "public_ip" {
  description = "Public IP of the trading server"
  value       = aws_eip.main.public_ip
}

output "alb_dns" {
  description = "ALB DNS name — access dashboard at http://<ALB-DNS>"
  value       = aws_lb.main.dns_name
}

output "dashboard_url" {
  description = "Direct URL to the trading dashboard"
  value       = "http://${aws_lb.main.dns_name}"
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.trading_server.id
}

output "rdp_command" {
  description = "RDP command to connect to the server"
  value       = "mstsc /v:${aws_eip.main.public_ip}"
}
