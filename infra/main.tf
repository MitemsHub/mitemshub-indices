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

# ─── Data: Latest Windows Server 2022 AMI ───────────────────────────
data "aws_ami" "windows_2022" {
  most_recent = true
  owners      = ["801119661308"] # Amazon Windows owner

  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ─── VPC (default) ──────────────────────────────────────────────────
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ─── Security Group ─────────────────────────────────────────────────
resource "aws_security_group" "trading_server" {
  name        = "mitemshub-trading-server-sg"
  description = "Allow SSH, HTTP, HTTPS for MitemsHub Trading System"
  vpc_id      = data.aws_vpc.default.id

  # RDP (for initial setup via AWS console)
  ingress {
    description = "RDP from admin IP"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["${var.admin_ip}/32"]
  }

  # HTTP (Cloudflare forwards to this)
  ingress {
    description = "HTTP from anywhere (for Cloudflare proxy)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS (Cloudflare forwards to this)
  ingress {
    description = "HTTPS from anywhere (for Cloudflare proxy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Next.js dev port (for direct access during setup)
  ingress {
    description = "Next.js dev port from admin IP"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["${var.admin_ip}/32"]
  }

  # All outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "mitemshub-trading-server-sg"
    Project = "MitemsHub Indices"
  }
}

# ─── IAM Role for EC2 (SSM access, CloudWatch logs) ────────────────
resource "aws_iam_role" "ec2_role" {
  name = "mitemshub-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "mitemshub-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# ─── EC2 Instance ───────────────────────────────────────────────────
resource "aws_instance" "trading_server" {
  ami                    = data.aws_ami.windows_2022.id
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.trading_server.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.ps1", {
    nodejs_version  = "20"
    python_version  = "3.12"
    app_port        = 3000
    github_repo_url = var.github_repo_url
  })

  tags = {
    Name    = "mitemshub-trading-server"
    Project = "MitemsHub Indices"
  }
}

# ─── Application Load Balancer ─────────────────────────────────────
resource "aws_lb" "trading_alb" {
  name               = "mitemshub-trading-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.trading_server.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Name    = "mitemshub-trading-alb"
    Project = "MitemsHub Indices"
  }
}

# ─── Target Group ───────────────────────────────────────────────────
resource "aws_lb_target_group" "trading_tg" {
  name     = "mitemshub-trading-tg"
  port     = var.app_port
  protocol = "HTTP"
  vpc_id   = data.aws_vpc.default.id

  health_check {
    path                = "/"
    port                = "traffic-port"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200-399"
  }

  tags = {
    Name    = "mitemshub-trading-tg"
    Project = "MitemsHub Indices"
  }
}

# ─── Target Group Attachment ────────────────────────────────────────
resource "aws_lb_target_group_attachment" "trading_attachment" {
  target_group_arn = aws_lb_target_group.trading_tg.arn
  target_id        = aws_instance.trading_server.id
  port             = var.app_port
}

# ─── HTTP Listener (port 80) ───────────────────────────────────────
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.trading_alb.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.trading_tg.arn
  }

  tags = {
    Name = "mitemshub-http-listener"
  }
}
