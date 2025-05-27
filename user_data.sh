#!/bin/bash

# EC2 User Data Script for Mobility Data Workers
# This script runs when EC2 instances start up

# Variables passed from Terraform
S3_BUCKET="${s3_bucket}"
QUEUE_URL="${queue_url}"
REGION="${region}"

# Update system
yum update -y

# Install Python 3.9 and pip
yum install -y python3 python3-pip

# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install

# Install required Python packages
pip3 install boto3 requests python-dotenv pytz

# Create working directory
mkdir -p /opt/mobility-worker
cd /opt/mobility-worker

# Download the mobility worker script from S3
aws s3 cp s3://${S3_BUCKET}/scripts/mobility_worker.py ./mobility_worker.py
aws s3 cp s3://${S3_BUCKET}/scripts/requirements.txt ./requirements.txt

# Install additional requirements if any
pip3 install -r requirements.txt

# Create environment variables file
cat > /opt/mobility-worker/.env << EOF
AWS_DEFAULT_REGION=${REGION}
SQS_QUEUE_URL=${QUEUE_URL}
S3_BUCKET=${S3_BUCKET}
EOF

# Create systemd service for the worker
cat > /etc/systemd/system/mobility-worker.service << EOF
[Unit]
Description=Mobility Data Worker
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/mobility-worker
Environment=PYTHONPATH=/opt/mobility-worker
Environment=AWS_DEFAULT_REGION=${REGION}
ExecStart=/usr/bin/python3 /opt/mobility-worker/mobility_worker.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
chown -R ec2-user:ec2-user /opt/mobility-worker
chmod +x /opt/mobility-worker/mobility_worker.py

# Enable and start the service
systemctl enable mobility-worker
systemctl start mobility-worker

# Create a script to check if queue is empty and shutdown instance
cat > /opt/mobility-worker/check_and_shutdown.sh << 'EOF'
#!/bin/bash

# Wait for the worker to finish processing
sleep 300  # Wait 5 minutes for any current job to start

# Check if SQS queue is empty and no jobs are running
QUEUE_MESSAGES=$(aws sqs get-queue-attributes --queue-url $SQS_QUEUE_URL --attribute-names ApproximateNumberOfVisibleMessages --output text --query 'Attributes.ApproximateNumberOfVisibleMessages')

if [ "$QUEUE_MESSAGES" -eq 0 ]; then
    # Check if worker process is still active
    if ! pgrep -f "mobility_worker.py" > /dev/null; then
        echo "No messages in queue and no active worker process. Shutting down instance."
        sudo shutdown -h +5  # Shutdown in 5 minutes
    fi
fi
EOF

chmod +x /opt/mobility-worker/check_and_shutdown.sh

# Add cron job to check for shutdown every 10 minutes
echo "*/10 * * * * /opt/mobility-worker/check_and_shutdown.sh" | crontab -

# Log startup completion
echo "Mobility worker instance startup completed at $(date)" >> /var/log/mobility-worker-startup.log