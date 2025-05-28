#!/bin/bash
set -x  # Only debug, do not exit on error

# Log all output to /var/log/user_data.log
exec > >(tee -a /var/log/user_data.log|logger -t user-data -s 2>/dev/console) 2>&1

# Always use ec2-user home
echo "[user_data] Changing to ec2-user home..."
cd /home/ec2-user || cd ~

# Install system dependencies
echo "[user_data] Installing system dependencies..."
sudo yum update -y
sudo yum install -y python3 python3-pip git nginx unzip curl

# Ensure latest AWS CLI v2 is installed (remove v1 if present)
echo "[user_data] Installing latest AWS CLI v2..."
sudo yum remove -y awscli || true
cd /tmp
curl -I https://github.com || { echo "[user_data] Network error: Cannot reach GitHub"; exit 1; }
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -o awscliv2.zip
sudo ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update
rm -rf awscliv2.zip aws
cd ~

# Confirm aws version
echo "[user_data] AWS CLI version:"
aws --version

# Clone or update the correct repo
REPO_URL="https://github.com/main-salman/mobility-data-lifecycle-manager.git"
REPO_DIR="mobility-data-lifecycle-manager"
echo "[user_data] Cloning or updating repo..."
if [ ! -d "$REPO_DIR" ]; then
  git clone "$REPO_URL" || { echo "[user_data] GIT CLONE FAILED"; exit 1; }
fi
cd "$REPO_DIR"

# Fix permissions if directory exists
echo "[user_data] Fixing permissions..."
if [ -d "/home/ec2-user/mobility-data-lifecycle-manager" ]; then
  sudo chown -R ec2-user:ec2-user /home/ec2-user/mobility-data-lifecycle-manager || true
  sudo chown ec2-user:ec2-user /home/ec2-user || true
else
  echo "[user_data] WARNING: Directory /home/ec2-user/mobility-data-lifecycle-manager does not exist for chown."
fi

# Create and activate virtualenv as ec2-user
echo "[user_data] Setting up Python virtual environment..."
if [ ! -d venv ]; then
  sudo -u ec2-user python3 -m venv venv
fi

# Install Python requirements as ec2-user
echo "[user_data] Installing Python requirements..."
sudo -u ec2-user bash -c 'source venv/bin/activate && pip install --upgrade pip && pip install flask boto3 python-dotenv requests'

# Fetch .env from AWS Secrets Manager (as ec2-user)
echo "[user_data] Fetching .env from AWS Secrets Manager..."
sudo -u ec2-user aws secretsmanager get-secret-value --secret-id mobility-data-lifecycle-env2 --region us-east-1 --query SecretString --output text > .env

# Parse SYNC_TIME from .env (format: HH:MM, 24h UTC)
echo "[user_data] Parsing SYNC_TIME and setting up cron..."
SYNC_TIME=$(grep '^SYNC_TIME' .env | cut -d'=' -f2 | tr -d "'\"")
SYNC_HOUR=$(echo $SYNC_TIME | cut -d: -f1)
SYNC_MIN=$(echo $SYNC_TIME | cut -d: -f2)

# Set up daily sync cron job (replace any previous daily_sync.py jobs)
echo "[user_data] Setting up cron job for daily sync..."
CRON_JOB="34 3 * * * cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && python daily_sync.py >> /home/ec2-user/mobility-data-lifecycle-manager/app.log 2>&1"
crontab -l | grep -v 'daily_sync.py' > /tmp/cron.tmp || true
if ! grep -Fxq "$CRON_JOB" /tmp/cron.tmp; then
  echo "$CRON_JOB" >> /tmp/cron.tmp
fi
crontab /tmp/cron.tmp
rm -f /tmp/cron.tmp

# Start Flask app as ec2-user (localhost:5050)
echo "[user_data] Starting Flask app..."
sudo -u ec2-user bash -c 'cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && nohup python3 flask_app.py > flask_app.log 2>&1 &'

# --- HTTPS/NGINX/LETSENCRYPT SETUP ---
APP_DOMAIN="${APP_DOMAIN:-mobility.qolimpact.click}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-salman.naqvi@gmail.com}"

echo "[user_data] Installing and configuring Nginx and Certbot..."
sudo amazon-linux-extras install -y nginx1 epel
sudo yum install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo yum install -y certbot

# Write HTTP config
echo "[user_data] Writing Nginx HTTP config..."
sudo tee /etc/nginx/conf.d/mobility.conf > /dev/null <<EOF
server {
    listen 80;
    server_name $APP_DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
sudo nginx -t
sudo systemctl restart nginx

# Obtain SSL certificate using certbot standalone
echo "[user_data] Obtaining SSL certificate..."
if [ ! -f "/etc/letsencrypt/live/$APP_DOMAIN/fullchain.pem" ]; then
  sudo systemctl stop nginx
  sudo certbot certonly --standalone --non-interactive --agree-tos --email $LETSENCRYPT_EMAIL -d $APP_DOMAIN
  sudo systemctl start nginx
fi

# Write HTTPS config
echo "[user_data] Writing Nginx HTTPS config..."
sudo tee /etc/nginx/conf.d/mobility-ssl.conf > /dev/null <<EOF
server {
    listen 443 ssl;
    server_name $APP_DOMAIN;
    ssl_certificate /etc/letsencrypt/live/$APP_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$APP_DOMAIN/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
sudo nginx -t
sudo systemctl reload nginx

# Set up auto-renewal
echo "[user_data] Setting up certbot auto-renewal..."
if ! sudo crontab -l | grep -q 'certbot renew'; then
  echo "0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'" | sudo crontab -
fi

echo "[user_data] Setup complete."