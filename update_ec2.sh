#!/bin/bash
set -e

# --- LOCAL GIT OPERATIONS ---
echo "--- Running local git commands... ---"

echo "Staging all changes..."
git add .

echo "Committing changes (if any)..."
# Only commit if there are staged changes, to avoid an error.
if ! git diff --cached --quiet; then
    git commit -m "updating app"
else
    echo "No changes to commit."
fi

echo "Pushing to remote..."
git push

echo "--- Local operations complete. Proceeding with EC2 update. ---"
echo ""

# --- CONFIGURATION ---
EC2_USER=ec2-user
EC2_HOST=3.224.127.136
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

# --- UPDATE PYTHON DEPENDENCIES ---
echo "Updating Python dependencies..."
# Install core dependencies
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"

# --- INSTALL GEOSPATIAL DEPENDENCIES FOR BOUNDARY UPLOAD ---
echo "Installing/updating geospatial dependencies for boundary upload..."
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && pip install numpy>=1.21.0 fiona>=1.8.0 shapely>=1.7.0 pyproj>=3.0.0 geopandas>=0.10.0"

# --- RENEW SSL CERTIFICATE IF NEEDED ---
echo "Checking and renewing SSL certificate if needed..."
# Check certificate status and renew if it expires within 30 days
ssh_cmd "sudo certbot renew --quiet || echo 'Certificate renewal check completed'"
# Reload nginx to apply any certificate changes
ssh_cmd "sudo nginx -t && sudo systemctl reload nginx"

# --- STOP EXISTING FLASK APP (install lsof if needed) ---
echo "Stopping any running Flask app (installing lsof if needed)..."
ssh_cmd "sudo yum install -y lsof && cd $PROJECT_DIR && if lsof -ti:5050 > /dev/null 2>&1; then kill \$(lsof -ti:5050); fi"
ssh_cmd "cd $PROJECT_DIR && PIDS=\$(ps aux | grep '[f]lask_app.py' | awk '{print \$2}'); if [ ! -z \"\$PIDS\" ]; then kill \$PIDS; fi"

# --- START FLASK APP ---
echo "Starting Flask app..."
ssh_cmd "cd $PROJECT_DIR && source venv/bin/activate && nohup python flask_app.py > flask_app.log 2>&1 &"

echo "Update complete! Flask app should be running on EC2: http://$EC2_HOST:5050"