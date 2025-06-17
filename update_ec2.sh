#!/bin/bash
set -e

# --- CONFIGURATION ---
EC2_USER=ec2-user
EC2_HOST=3.228.4.143
EC2_KEY=salman-dev.pem
PROJECT_DIR=/home/ec2-user/mobility-data-lifecycle-manager/   # Change if your project is in a different location

# --- SSH COMMAND WRAPPER ---
ssh_cmd() {
  ssh -n -i "$EC2_KEY" "$EC2_USER@$EC2_HOST" "$@"
}

echo "Connecting to $EC2_USER@$EC2_HOST..."

# --- GIT PULL LATEST CODE ---
echo "Pulling latest code from GitHub..."
ssh_cmd "cd $PROJECT_DIR && git pull"

# --- ENSURE /db DIRECTORY EXISTS ---
echo "Ensuring /db directory exists..."
ssh_cmd "cd $PROJECT_DIR && mkdir -p db"

# --- OPTIONAL: UPDATE PYTHON DEPENDENCIES ---
echo "Updating Python dependencies..."
# Try requirements.txt, fallback to explicit install if missing
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && (pip install --upgrade pip && pip install -r requirements.txt || pip install flask boto3 python-dotenv requests gunicorn)"

# --- STOP EXISTING FLASK APP (install lsof if needed) ---
echo "Stopping any running Flask app (installing lsof if needed)..."
ssh_cmd "sudo yum install -y lsof && cd $PROJECT_DIR && if lsof -ti:5050 > /dev/null 2>&1; then kill \$(lsof -ti:5050); fi"
ssh_cmd "cd $PROJECT_DIR && PIDS=\$(ps aux | grep '[f]lask_app.py' | awk '{print \$2}'); if [ ! -z \"\$PIDS\" ]; then kill \$PIDS; fi"

# --- START FLASK APP ---
echo "Starting Flask app..."
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && nohup python flask_app.py > flask_app.log 2>&1 &"

echo "Update complete! Flask app should be running on EC2: http://$EC2_HOST:5050"