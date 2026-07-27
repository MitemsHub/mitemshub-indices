# Cloudflare Setup Guide (Step-by-Step for Newbies)

## What Is Cloudflare and Why Do We Need It?

Cloudflare is a free service that sits between your website and your visitors. It provides:
- **Free SSL certificate** (the padlock 🔒 in the browser)
- **Free CDN** (makes your site load faster worldwide)
- **DDoS protection** (keeps hackers away)
- **Free DNS** (translates your domain name to the server address)

Think of it as a security guard + speed booster for your website.

---

## Step 1: Create a Cloudflare Account

1. Go to **https://dash.cloudflare.com/sign-up**
2. Enter your email address and create a password
3. Verify your email by clicking the link they send you

---

## Step 2: Add Your Domain

1. Log into Cloudflare
2. Click **"Add a Site"** (top right or center of dashboard)
3. Type your domain name: **mitemshub-indices.com**
4. Click **"Add Site"**
5. Select the **Free** plan (it's enough for us!)
6. Click **"Continue"**

---

## Step 3: Update Your Domain's Nameservers

Cloudflare will show you two nameserver addresses. You need to update these at your domain registrar (where you bought the domain).

### If you bought the domain from Namecheap:
1. Go to Namecheap → Domain List → Manage
2. Scroll to "NAMESERVERS"
3. Select "Custom DNS"
4. Paste the two Cloudflare nameservers
5. Click the green checkmark to save

### If you bought the domain from GoDaddy:
1. Go to GoDaddy → My Products → DNS
2. Click "Nameservers" → "Change"
3. Select "Custom" and enter the Cloudflare nameservers
4. Save

### If you bought the domain from Google Domains:
1. Go to Google Domains → DNS
2. Click "Name servers" → "Use custom name servers"
3. Enter the Cloudflare nameservers
4. Save

**Wait 5-30 minutes** for the nameserver changes to propagate.

---

## Step 4: Add DNS Record (CNAME)

Once Cloudflare verifies the nameservers (you'll see a green checkmark):

1. Go to **DNS** → **Records** in the Cloudflare dashboard
2. Click **"Add Record"**
3. Fill in:
   - **Type:** `CNAME`
   - **Name:** `@` (this means the root domain)
   - **Target:** Your ALB DNS name (from Terraform output, looks like: `mitemshub-trading-alb-xxxxx.eu-north-1.elb.amazonaws.com`)
   - **Proxy status:** ON (orange cloud ☁️)
4. Click **"Save"**

---

## Step 5: Set SSL/TLS Mode

1. Go to **SSL/TLS** → **Overview**
2. Select **"Full (Strict)"**
3. This tells Cloudflare to use HTTPS end-to-end

---

## Step 6: Enable HTTPS Redirect

1. Go to **SSL/TLS** → **Edge Certificates**
2. Scroll to "Always Use HTTPS"
3. Toggle it **ON**

---

## Step 7: Test It!

1. Wait 5 minutes for everything to propagate
2. Open your browser and go to: **https://mitemshub-indices.com**
3. You should see the MitemsHub Trading Dashboard
4. Check the address bar — you should see the padlock 🔒

---

## Troubleshooting

### "Server not responding" error
- Make sure the EC2 instance is running
- Check that the ALB target group shows the instance as "healthy"
- Verify the security group allows port 80

### SSL certificate error
- Make sure SSL/TLS mode is set to "Full (Strict)"
- Wait 10 minutes and try again

### Domain not resolving
- Verify nameservers are updated at your registrar
- Check DNS records in Cloudflare
- Use https://www.whatsmydns.net to check propagation

### Need help?
- Go to Cloudflare → Support → Enter your question
- Or ask me and I'll help you debug!
