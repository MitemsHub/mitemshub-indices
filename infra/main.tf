# ── Terraform State ─────────────────────────────────────────────
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ── Provider ───────────────────────────────────────────────────
provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

# ── Data Sources ───────────────────────────────────────────────
data "aws_ami" "windows_2022" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── Security Group — EC2 ──────────────────────────────────────
resource "aws_security_group" "trading_server" {
  name        = "mitemshub-trading-server"
  description = "Security group for the Synthetic Indices Trading Server"

  # HTTP from ALB only
  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "HTTP from ALB"
  }

  # Next.js from ALB only
  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Next.js from ALB"
  }

  # RDP — restricted to admin IP
  ingress {
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["${var.admin_ip}/32"]
    description = "RDP (restricted to admin IP)"
  }

  # MT5 IPC port (local only)
  ingress {
    from_port   = 22346
    to_port     = 22346
    protocol    = "tcp"
    self        = true
    description = "MT5 MCP server (local only)"
  }

  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name    = "mitemshub-trading-server"
    Project = "SyntheticIndicesBot"
  }
}

# ── Security Group — ALB ──────────────────────────────────────
resource "aws_security_group" "alb" {
  name        = "mitemshub-alb"
  description = "Security group for the Application Load Balancer"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name    = "mitemshub-alb"
    Project = "SyntheticIndicesBot"
  }
}

# ── ALB ────────────────────────────────────────────────────────
resource "aws_lb" "main" {
  name               = "mitemshub-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Name    = "mitemshub-alb"
    Project = "SyntheticIndicesBot"
  }
}

# ── Target Group ───────────────────────────────────────────────
resource "aws_lb_target_group" "app" {
  name     = "mitemshub-app"
  port     = 3000
  protocol = "HTTP"
  vpc_id   = data.aws_vpc.default.id

  health_check {
    enabled             = true
    path                = "/api/system/status"
    port                = "3000"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name    = "mitemshub-app"
    Project = "SyntheticIndicesBot"
  }
}

# ── ALB Listener — HTTP ───────────────────────────────────────
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# ── EC2 Instance ──────────────────────────────────────────────
resource "aws_instance" "trading_server" {
  ami                    = data.aws_ami.windows_2022.id
  instance_type          = "t3.large"
  vpc_security_group_ids = [aws_security_group.trading_server.id]
  subnet_id              = data.aws_subnets.default.ids[0]

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user_data.ps1", {
    github_repo     = "https://github.com/MitemsHub/mitemshub-indices.git"
    github_branch   = "feature/mt5-rollout-enablement"
    mt5_server      = var.mt5_server
    mt5_login       = var.mt5_login
    mt5_password    = var.mt5_password
  })

  tags = {
    Name    = "mitemshub-trading-server"
    Project = "SyntheticIndicesBot"
  }
}

# ── Elastic IP ────────────────────────────────────────────────
resource "aws_eip" "main" {
  instance = aws_instance.trading_server.id
  domain   = "vpc"

  tags = {
    Name    = "mitemshub-eip"
    Project = "SyntheticIndicesBot"
  }
}
