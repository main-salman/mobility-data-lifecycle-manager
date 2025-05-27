#!/bin/bash
set -e

# 1. Install system dependencies
sudo yum update -y
sudo yum install -y python3 git awscli

# 2. Set up Python virtual environment
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate

# 3. Install Python requirements
pip install --upgrade pip
pip install flask boto3 python-dotenv requests gunicorn

# 4. Ensure all project files are present (assume uploaded to instance)
for f in flask_app.py sync_logic.py dynamodb_create_table.py .env; do
  if [ ! -f "$f" ]; then
    echo "ERROR: $f not found. Please upload all project files to the instance."
    exit 1
  fi
done

# 5. Create DynamoDB table (idempotent)
python dynamodb_create_table.py

# 6. Create SNS topic and subscribe email (idempotent)
SNS_TOPIC_NAME="mobility-sync-alerts"
SNS_EMAIL="salman.naqvi@gmail.com"
SNS_TOPIC_ARN=$(aws sns create-topic --name $SNS_TOPIC_NAME --output text)
aws sns subscribe --topic-arn $SNS_TOPIC_ARN --protocol email --notification-endpoint $SNS_EMAIL || true
# Add SNS_TOPIC_ARN to .env if not present
grep -q SNS_TOPIC_ARN .env || echo "SNS_TOPIC_ARN=$SNS_TOPIC_ARN" >> .env

# 7. Set up Flask app as a systemd service
cat <<EOF | sudo tee /etc/systemd/system/flask_app.service
[Unit]
Description=Flask Mobility Sync App
After=network.target

[Service]
User=ec2-user
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/venv/bin"
ExecStart=$(pwd)/venv/bin/python flask_app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable flask_app.service
sudo systemctl restart flask_app.service

# 8. Create daily_sync.py for daily syncs (to be used with cron)
cat <<'PYEOF' > daily_sync.py
import boto3
from datetime import datetime, timedelta
from flask_app import get_table
from sync_logic import sync_city_for_date

def main():
    table = get_table()
    resp = table.scan()
    cities = resp.get('Items', [])
    # Use yesterday in each city's local time (for now, use UTC)
    date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    for city in cities:
        print(f"Syncing {city['city']} for {date}")
        result = sync_city_for_date(city, date)
        print(f"Result: {'Success' if result else 'Failed'}")

if __name__ == "__main__":
    main()
PYEOF

chmod +x daily_sync.py

# 9. Print final instructions
cat <<EOM

---
SETUP COMPLETE!

Manual steps remaining:
1. Go to S3 Console > veraset-data-qoli-dev > Management > Lifecycle rules:
   - Add a rule to delete objects older than 7 days
2. Confirm the SNS subscription in your email (salman.naqvi@gmail.com)

To access the Flask UI:
- SSH tunnel: ssh -i salman-dev.pem -L 5000:localhost:5000 ec2-user@<EC2_PUBLIC_IP>
- Open http://localhost:5000 in your browser

To run daily sync for all cities (add to crontab):
  0 2 * * * cd $(pwd) && source venv/bin/activate && python daily_sync.py

See README.md for more details.
---
EOM 