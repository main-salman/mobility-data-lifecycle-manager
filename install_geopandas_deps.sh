#!/bin/bash
set -e

# Script to install GeoPandas system dependencies on Amazon Linux EC2
echo "Installing GeoPandas system dependencies on EC2..."

# Configuration
EC2_USER=ec2-user
EC2_HOST=3.224.127.136
EC2_KEY=salman-dev.pem
PROJECT_DIR=/home/ec2-user/mobility-data-lifecycle-manager/

# SSH command wrapper
ssh_cmd() {
  ssh -n -i "$EC2_KEY" "$EC2_USER@$EC2_HOST" "$@"
}

echo "Connecting to $EC2_USER@$EC2_HOST..."

# Install system dependencies for GeoPandas
echo "Installing system dependencies via yum..."
ssh_cmd "sudo yum update -y"
ssh_cmd "sudo yum install -y gcc gcc-c++ python3-devel"
ssh_cmd "sudo yum install -y gdal gdal-devel geos geos-devel proj proj-devel"
ssh_cmd "sudo yum install -y sqlite-devel"

# Install Python dependencies in virtual environment
echo "Installing Python geospatial packages..."
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install --upgrade pip setuptools wheel"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install numpy>=1.21.0"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install fiona>=1.8.0"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install shapely>=1.7.0"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install pyproj>=3.0.0"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install geopandas>=0.10.0"

# Restart Flask app to pick up new dependencies
echo "Restarting Flask application..."
ssh_cmd "cd $PROJECT_DIR && if lsof -ti:5050 > /dev/null 2>&1; then kill \$(lsof -ti:5050); fi"
ssh_cmd "cd $PROJECT_DIR && PIDS=\$(ps aux | grep '[f]lask_app.py' | awk '{print \$2}'); if [ ! -z \"\$PIDS\" ]; then kill \$PIDS; fi"
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && nohup python flask_app.py > flask_app.log 2>&1 &"

echo "GeoPandas installation complete! Boundary upload should now be available."
echo "Check the app at: http://$EC2_HOST:5050" 