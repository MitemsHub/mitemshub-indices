output "alb_dns_name" {
  description = "DNS name of the ALB (point Cloudflare CNAME here)"
  value       = aws_lb.trading_alb.dns_name
}

output "alb_zone_id" {
  description = "Zone ID of the ALB (for Route53 alias records)"
  value       = aws_lb.trading_alb.zone_id
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.trading_server.id
}

output "instance_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = aws_instance.trading_server.private_ip
}

output "security_group_id" {
  description = "Security group ID (for manual rule updates)"
  value       = aws_security_group.trading_server.id
}

output "setup_instructions" {
  description = "Next steps after terraform apply"
  value = <<-EOT

    ======================================
     DEPLOYMENT COMPLETE
    ======================================

    1. ALB DNS: ${aws_lb.trading_alb.dns_name}
       → Point your Cloudflare CNAME to this address

    2. Instance ID: ${aws_instance.trading_server.id}
       → Connect via AWS Console → RDP (port 3389)

    3. After connecting via RDP:
       → Open PowerShell as Administrator
       → Run: C:\deploy\setup.ps1
       → This clones the repo, installs deps, and starts the app

    4. Cloudflare Setup:
       → Add CNAME record: @ → ${aws_lb.trading_alb.dns_name}
       → Enable proxy (orange cloud)
       → SSL/TLS mode: Full (Strict)

    5. Access your dashboard at: https://mitemshub-indices.com
  EOT
}
