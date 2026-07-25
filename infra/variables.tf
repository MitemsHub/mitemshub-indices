# ── AWS Credentials (from environment) ─────────────────────────
variable "aws_access_key" {
  description = "AWS Access Key ID"
  type        = string
  sensitive   = true
}

variable "aws_secret_key" {
  description = "AWS Secret Access Key"
  type        = string
  sensitive   = true
}

# ── AWS Region ─────────────────────────────────────────────────
variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-north-1"
}

# ── Admin IP for RDP access ───────────────────────────────────
variable "admin_ip" {
  description = "Your public IP for RDP access (find it at whatismyip.com)"
  type        = string
}

# ── MT5 Configuration ─────────────────────────────────────────
variable "mt5_server" {
  description = "MT5 broker server name"
  type        = string
}

variable "mt5_login" {
  description = "MT5 account login"
  type        = string
}

variable "mt5_password" {
  description = "MT5 account password"
  type        = string
  sensitive   = true
}
