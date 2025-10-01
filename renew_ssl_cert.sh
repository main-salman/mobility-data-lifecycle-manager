#!/bin/bash
set -e

# --- CONFIGURATION ---
EC2_USER=ec2-user
EC2_HOST=3.224.127.136
EC2_KEY=salman-dev.pem
APP_DOMAIN=mobility.qolimpact.click

# --- SSH COMMAND WRAPPER ---
ssh_cmd() {
  ssh -n -i "$EC2_KEY" "$EC2_USER@$EC2_HOST" "$@"
}

echo "=== SSL Certificate Renewal for $APP_DOMAIN ==="
echo "Connecting to $EC2_USER@$EC2_HOST..."

# --- CHECK CURRENT CERTIFICATE STATUS ---
echo "Checking current certificate status..."
ssh_cmd "sudo certbot certificates"

# --- FORCE RENEW EXPIRED CERTIFICATE ---
echo "Force renewing SSL certificate..."
# Stop nginx temporarily for standalone renewal
ssh_cmd "sudo systemctl stop nginx"

# Wait a moment for port to be free
sleep 2

# Use certbot standalone to renew certificate (works even if expired)
echo "Running certbot standalone renewal..."
ssh_cmd "sudo certbot certonly --standalone --force-renewal --non-interactive --agree-tos --email salman.naqvi@gmail.com -d $APP_DOMAIN || echo 'Certbot renewal attempted'"

# Start nginx back up
echo "Starting nginx..."
ssh_cmd "sudo systemctl start nginx"

# Test nginx configuration
ssh_cmd "sudo nginx -t"

# Reload nginx to use new certificate
ssh_cmd "sudo systemctl reload nginx"

# --- VERIFY CERTIFICATE RENEWAL ---
echo "Verifying certificate renewal..."
ssh_cmd "sudo certbot certificates | grep -A10 '$APP_DOMAIN'"

# --- TEST HTTPS ACCESS ---
echo "Testing HTTPS access..."
curl -I --connect-timeout 10 "https://$APP_DOMAIN" || echo "HTTPS test failed - check manually"

echo "=== SSL Certificate Renewal Complete ==="
echo "Your site should now be accessible at: https://$APP_DOMAIN"
echo ""
echo "The certificate should auto-renew in the future via the existing cron job:"
echo "0 3 * * * certbot renew --quiet --post-hook 'nginx -t && systemctl reload nginx'"
