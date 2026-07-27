# MitemsHub Indices — Cloud Deployment Guide

## Architecture Overview

```
Your Phone/Laptop/Tablet (any device, anywhere)
        │
        ▼ HTTPS (port 443)
   Cloudflare (free domain + free SSL + CDN + DDoS protection)
        │
        ▼ HTTP (port 80)
   AWS ALB (Application Load Balancer)
        │
        ▼
   AWS EC2 t3.micro (Windows Server 2022)
   ├── Next.js dashboard (port 3000)
   ├── Python trading engine
   └── MT5 terminal (data source)
```

## Prerequisites

- [x] AWS account with free tier (6 months)
- [x] Cloudflare account (free)
- [x] Domain name: `mitemshub-indices.com`
- [x] Terraform installed locally
- [x] Your public IP: `102.91.77.77`

## Step-by-Step Deployment

### 1. Configure Terraform Variables

```bash
cd infra/
```

Create a `terraform.tfvars` file (DO NOT commit this to git):

```hcl
aws_region    = "eu-north-1"
instance_type = "t3.micro"
admin_ip      = "102.91.77.77"
app_port      = 3000
github_repo_url = "https://github.com/YOUR_USERNAME/Synthetic-Indices-Bot.git"
```

### 2. Set AWS Credentials

Set environment variables (DO NOT hardcode in files):

```bash
export AWS_ACCESS_KEY_ID="YOUR_ACCESS_KEY_HERE"
export AWS_SECRET_ACCESS_KEY="YOUR_SECRET_KEY_HERE"
export AWS_DEFAULT_REGION="eu-north-1"
```

### 3. Initialize Terraform

```bash
cd infra/
terraform init
```

### 4. Preview the Plan

```bash
terraform plan
```

Review what will be created:
- EC2 instance (t3.micro Windows Server 2022)
- Security group (RDP + HTTP + HTTPS)
- Application Load Balancer
- Target group + health checks
- IAM role for SSM access

### 5. Deploy

```bash
terraform apply
```

Type `yes` when prompted. This takes 3-5 minutes.

### 6. Connect to the Server

After Terraform completes, note the ALB DNS name from the output.

1. Go to **AWS Console** → **EC2** → **Instances**
2. Select "mitemshub-trading-server"
3. Click **"Connect"** → **"RDP Client"**
4. Download the RDP file
5. Open it with Microsoft Remote Desktop
6. Username: `Administrator`
7. Password: Get it from AWS Console → EC2 → Key Pairs (or use "Get Windows Password")

### 7. First-Time Server Setup

Once connected via RDP:

1. Open **PowerShell as Administrator**
2. Run:
   ```powershell
   C:\deploy\setup.ps1
   ```
3. Wait for the script to finish (installs Node.js, Python, Git, clones repo, builds app)
4. The dashboard will be available at `http://localhost:3000`

### 8. Configure Cloudflare

See [CLOUDFLARE_SETUP.md](./CLOUDFLARE_SETUP.md) for detailed instructions.

**Quick summary:**
1. Add your domain to Cloudflare
2. Update nameservers at your registrar
3. Add CNAME record: `@` → ALB DNS name (enable proxy)
4. Set SSL/TLS mode to "Full (Strict)"
5. Enable "Always Use HTTPS"

### 9. Verify Deployment

1. Wait 5-10 minutes for DNS propagation
2. Go to **https://mitemshub-indices.com**
3. You should see the MitemsHub Trading Dashboard
4. The padlock 🔒 should appear in the address bar

---

## Cost Summary

| Item | Cost | Notes |
|------|------|-------|
| EC2 t3.micro | **FREE** | 750 hrs/month for 12 months (free tier) |
| ALB | ~$16/month | Covered by your 6-month AWS credit |
| Cloudflare | **FREE** | SSL, CDN, DNS, DDoS protection |
| **Total** | **~$0/month** | Within free tier + credits |

---

## Updating the Application

To deploy code changes after the initial setup:

```bash
# Via RDP
cd C:\app
git pull
cd external\mitemshub-indices
npm install
npm run build
pm2 restart mitemshub
```

Or via AWS SSM (no RDP needed):
```bash
aws ssm send-command \
  --instance-ids <INSTANCE_ID> \
  --document-name "AWS-RunPowerShellScript" \
  --parameters 'commands=["cd C:\\app && git pull && cd external\\mitemshub-indices && npm install && npm run build && pm2 restart mitemshub"]'
```

---

## Shutting Down

To avoid charges after testing:

```bash
terraform destroy
```

Type `yes` when prompted. This removes all AWS resources.

---

## Troubleshooting

### "Bridge Offline" error in dashboard
- The Python engine needs MT5 terminal running
- On AWS, MT5 won't work (no GUI) — use "Paper" mode instead
- Or connect to a local MT5 via API

### Server won't start after reboot
- PM2 should auto-start the app
- If not, RDP in and run: `pm2 resurrect`

### Can't connect via RDP
- Check security group allows port 3389 from your IP
- Your IP may have changed — update the security group

### Cloudflare 502 error
- The ALB target may be unhealthy
- Check EC2 instance is running
- Verify the app is listening on port 3000
