#!/bin/bash
set -ex

# Log all output to /var/log/user_data.log
exec > >(tee -a /var/log/user_data.log|logger -t user-data -s 2>/dev/console) 2>&1

# Always use ec2-user home
cd /home/ec2-user || cd ~

# Install system dependencies
sudo yum update -y
sudo yum install -y python3 python3-pip python3-venv git awscli

# Clone or update the correct repo
REPO_URL="https://github.com/main-salman/mobility-data-lifecycle-manager.git"
REPO_DIR="mobility-data-lifecycle-manager"
echo "[user_data] Cloning or updating repo..."
if [ ! -d "$REPO_DIR" ]; then
  git clone "$REPO_URL"
else
  cd "$REPO_DIR"
  git pull origin main
  cd ..
fi
cd "$REPO_DIR"

# Create and activate virtualenv as ec2-user
sudo -u ec2-user python3 -m venv venv
sudo chown -R ec2-user:ec2-user venv .

# Install Python requirements as ec2-user
echo "[user_data] Installing Python requirements..."
sudo -u ec2-user bash -c 'source venv/bin/activate && pip install --upgrade pip && if [ -f requirements.txt ]; then pip install -r requirements.txt; else pip install flask boto3 python-dotenv requests; fi'

# Fetch .env from AWS Secrets Manager (as root, but chown to ec2-user)
echo "[user_data] Fetching .env from AWS Secrets Manager..."
SECRET_NAME=$${AWS_ENV_SECRET_NAME:-mobility-data-lifecycle-env}
REGION=$${AWS_REGION:-us-east-1}
aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --region "$REGION" --query SecretString --output text > .env
sudo chown ec2-user:ec2-user .env

# Parse SYNC_TIME from .env (format: HH:MM, 24h UTC)
echo "[user_data] Parsing SYNC_TIME and setting up cron..."
SYNC_TIME=$(grep '^SYNC_TIME' .env | cut -d'=' -f2 | tr -d "'\"")
SYNC_HOUR=$(echo $SYNC_TIME | cut -d: -f1)
SYNC_MIN=$(echo $SYNC_TIME | cut -d: -f2)

CRON_CMD="cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && python3 daily_sync.py >> daily_sync.log 2>&1"
crontab -l | grep -v 'daily_sync.py' | grep -v 'venv/bin/activate' > mycron || true
if [ -n "$SYNC_HOUR" ] && [ -n "$SYNC_MIN" ]; then
  echo "$SYNC_MIN $SYNC_HOUR * * * $CRON_CMD" >> mycron
  crontab mycron
fi
rm -f mycron

# Start Flask app as ec2-user
echo "[user_data] Starting Flask app..."
sudo -u ec2-user bash -c 'cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && nohup python3 flask_app.py > flask_app.log 2>&1 &'