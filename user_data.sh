#!/bin/bash
set -x

echo "[user_data] Script started at $(date)"

# Simple output redirection for compatibility with both cloud-init and manual runs
# (If running manually, output will go to /var/log/user_data.log)
#exec > /var/log/user_data.log 2>&1

# Only redirect output if running under cloud-init (i.e., as user-data)
#if [ -f /var/lib/cloud/instance/user-data.txt ] && grep -q "$0" /proc/$$/cmdline; then
#  exec > >(tee -a /var/log/user_data.log|logger -t user-data -s 2>/dev/console) 2>&1
#else
  # For manual runs, just print to terminal
#  echo "[user_data] Running in manual/debug mode, not redirecting output."
#fi

# System dependencies
sudo yum update -y
sudo yum install -y git nginx unzip curl
# Install Python 3.8 (required for the application)
sudo amazon-linux-extras install python3.8 -y
sudo yum install -y python3.8-pip
# Create symlinks for easier usage
sudo ln -sf /usr/bin/python3.8 /usr/local/bin/python3
sudo ln -sf /usr/bin/pip3.8 /usr/local/bin/pip3

# Install GeoPandas system dependencies for boundary upload functionality
echo "[user_data] Installing GeoPandas system dependencies..."
sudo yum install -y gcc gcc-c++ python38-devel
sudo yum install -y gdal gdal-devel geos geos-devel proj proj-devel
sudo yum install -y sqlite-devel

# --- CloudWatch Agent Installation and Configuration ---
echo "[user_data] Installing Amazon CloudWatch Agent..."
sudo yum install -y amazon-cloudwatch-agent
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
CLOUDWATCH_CONFIG_FILE="/opt/aws/amazon-cloudwatch-agent/bin/config.json"

sudo mkdir -p /opt/aws/amazon-cloudwatch-agent/bin
sudo tee $CLOUDWATCH_CONFIG_FILE > /dev/null <<EOF
{
  "metrics": {
    "namespace": "CWAgent",
    "metrics_collected": {
      "cpu": {
        "measurement": ["cpu_usage_idle", "cpu_usage_iowait", "cpu_usage_user", "cpu_usage_system"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["used_percent", "inodes_free"],
        "metrics_collection_interval": 60,
        "resources": ["*"]
      },
      "diskio": {
        "measurement": ["io_time"],
        "metrics_collection_interval": 60,
        "resources": ["*"]
      },
      "mem": {
        "measurement": ["mem_used_percent"],
        "metrics_collection_interval": 60
      },
      "netstat": {
        "measurement": ["tcp_established", "tcp_time_wait"]
      },
      "swap": {
        "measurement": ["swap_used_percent"],
        "metrics_collection_interval": 60
      }
    }
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {"file_path": "/var/log/messages", "log_group_name": "/mobility/manager", "log_stream_name": "$INSTANCE_ID-messages"},
          {"file_path": "/var/log/cloud-init.log", "log_group_name": "/mobility/manager", "log_stream_name": "$INSTANCE_ID-cloudinit"},
          {"file_path": "/home/ec2-user/mobility-data-lifecycle-manager/flask_app.log", "log_group_name": "/mobility/manager", "log_stream_name": "$INSTANCE_ID-flask"}
        ]
      }
    }
  }
}
EOF

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:$CLOUDWATCH_CONFIG_FILE -s

# Enable CloudWatch Agent to start on boot
sudo systemctl enable amazon-cloudwatch-agent

# AWS CLI v2
sudo yum remove -y awscli || true
cd /tmp
curl -I https://github.com
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -o awscliv2.zip
sudo ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update
rm -rf awscliv2.zip aws
cd ~

export PATH=$PATH:/usr/local/bin

echo "[user_data] AWS CLI version:"
aws --version

sudo rm -f /home/ec2-user/mobility-data-lifecycle-manager/.env
# Fetch .env as ec2-user so it is always owned by ec2-user
sudo -u ec2-user bash -c 'export PATH=$PATH:/usr/local/bin; aws secretsmanager get-secret-value --secret-id mobility-data-lifecycle-env2 --region us-east-1 --query SecretString --output text > /home/ec2-user/mobility-data-lifecycle-manager/.env'
sudo chown ec2-user:ec2-user /home/ec2-user/mobility-data-lifecycle-manager/.env
sudo chmod 600 /home/ec2-user/mobility-data-lifecycle-manager/.env
# All project setup as ec2-user in /home/ec2-user using a temporary script to avoid quoting issues
cat > /home/ec2-user/ec2_setup.sh <<'EOF'
cd /home/ec2-user
export PATH=$PATH:/usr/local/bin
echo "[user_data] Cloning or updating repo..."
if [ ! -d "mobility-data-lifecycle-manager" ]; then
  git clone https://github.com/main-salman/mobility-data-lifecycle-manager.git
fi
cd mobility-data-lifecycle-manager

echo "[user_data] Setting up Python virtual environment..."
if [ ! -d venv ]; then
  python3.8 -m venv venv
fi

echo "[user_data] Installing Python requirements..."
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install flask boto3 python-dotenv requests
pip install geojson

# Install geospatial packages for boundary upload functionality
echo "[user_data] Installing geospatial Python packages..."
pip install numpy>=1.21.0
pip install fiona>=1.8.0
pip install shapely>=1.7.0
pip install pyproj>=3.0.0
pip install geopandas>=0.10.0

echo "[user_data] Parsing SYNC_TIME and setting up cron..."
SYNC_TIME=$(grep '^SYNC_TIME' .env | cut -d'=' -f2 | tr -d "'\"")
SYNC_HOUR=$(echo $SYNC_TIME | cut -d: -f1)
SYNC_MIN=$(echo $SYNC_TIME | cut -d: -f2)
CRON_JOB="$SYNC_MIN $SYNC_HOUR * * * cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && source .env && python daily_sync.py >> /home/ec2-user/mobility-data-lifecycle-manager/app.log 2>&1"
(crontab -l 2>/dev/null | grep -v "daily_sync.py" || true) > /tmp/cron.tmp
if ! grep -Fxq "$CRON_JOB" /tmp/cron.tmp; then
  echo "$CRON_JOB" >> /tmp/cron.tmp
fi
crontab /tmp/cron.tmp
rm -f /tmp/cron.tmp

echo "[user_data] Starting Flask app..."
nohup python3 flask_app.py > flask_app.log 2>&1 &
EOF

sudo chown -R ec2-user:ec2-user /home/ec2-user/mobility-data-lifecycle-manager
sudo chown ec2-user:ec2-user /home/ec2-user/ec2_setup.sh
sudo chmod +x /home/ec2-user/ec2_setup.sh
sudo -u ec2-user bash /home/ec2-user/ec2_setup.sh
sudo rm -f /home/ec2-user/ec2_setup.sh

# --- HTTPS/NGINX/LETSENCRYPT SETUP ---
APP_DOMAIN="$${APP_DOMAIN:-mobility.qolimpact.click}"
LETSENCRYPT_EMAIL="$${LETSENCRYPT_EMAIL:-salman.naqvi@gmail.com}"
echo "[user_data] Installing and configuring Nginx and Certbot..."
sudo amazon-linux-extras install -y nginx1 epel
sudo yum install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo yum install -y certbot

# Wait for network connectivity before proceeding
echo "[user_data] Checking network connectivity..."
for i in {1..10}; do
  curl -I https://github.com && break
  echo "[user_data] Network not ready, retrying in 5s... $i/10"
  sleep 5
done

# Start nginx and wait for it to be active
echo "[user_data] Starting nginx..."
sudo systemctl start nginx
for i in {1..10}; do
  sudo systemctl is-active --quiet nginx && break
  echo "[user_data] Waiting for nginx to become active... $i/10"
  sleep 2
done

# Write HTTP config
echo "[user_data] Writing Nginx HTTP config..."
sudo tee /etc/nginx/conf.d/mobility.conf > /dev/null <<EOF
server {
    listen 80;
    server_name $APP_DOMAIN;
    client_max_body_size 50M;  # Allow large file uploads
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;  # 5 minute timeout for large uploads
        proxy_send_timeout 300;
    }
}
EOF
sudo nginx -t
sudo systemctl restart nginx

# Obtain SSL certificate using certbot standalone
echo "[user_data] Obtaining SSL certificate..."
if [ ! -f "/etc/letsencrypt/live/$APP_DOMAIN/fullchain.pem" ]; then
  sudo systemctl stop nginx
  sudo certbot certonly --standalone --non-interactive --agree-tos --email $LETSENCRYPT_EMAIL -d $APP_DOMAIN || {
    echo "[user_data] Certbot failed. Check logs for details.";
    sudo systemctl start nginx;
    exit 1;
  }
  sudo systemctl start nginx
  sudo nginx -t && sudo systemctl reload nginx
fi

# Write HTTPS config
echo "[user_data] Writing Nginx HTTPS config..."
sudo tee /etc/nginx/conf.d/mobility-ssl.conf > /dev/null <<EOF
server {
    listen 443 ssl;
    server_name $APP_DOMAIN;
    ssl_certificate /etc/letsencrypt/live/$APP_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$APP_DOMAIN/privkey.pem;
    client_max_body_size 50M;  # Allow large file uploads
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;  # 5 minute timeout for large uploads
        proxy_send_timeout 300;
    }
}
EOF
sudo nginx -t
sudo systemctl reload nginx

# Set up auto-renewal
echo "[user_data] Setting up certbot auto-renewal..."
if ! sudo crontab -l | grep -q 'certbot renew'; then
  echo "0 3 * * * certbot renew --quiet --post-hook 'nginx -t && systemctl reload nginx'" | sudo crontab -
fi

# Ensure passwordless sudo for crontab for ec2-user
echo "ec2-user ALL=(ALL) NOPASSWD: /usr/bin/crontab" | sudo tee /etc/sudoers.d/mobility-flask-crontab > /dev/null

echo "[user_data] .env already fetched and permissions set."
echo "[user_data] Setup complete."