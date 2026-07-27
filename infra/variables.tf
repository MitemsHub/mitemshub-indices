variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-north-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "admin_ip" {
  description = "Your public IP for initial RDP access (format: x.x.x.x)"
  type        = string
}

variable "app_port" {
  description = "Port the Next.js app runs on"
  type        = number
  default     = 3000
}

variable "github_repo_url" {
  description = "GitHub repo URL to clone on the server"
  type        = string
  default     = "https://github.com/USER/Synthetic-Indices-Bot.git"
}
