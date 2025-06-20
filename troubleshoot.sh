#!/bin/bash
# Troubleshooter for daily_sync.py on EC2
#
# How to run on the EC2 instance:
# 1. Place this script in the project root directory (e.g., /home/ec2-user/mobility-data-lifecycle-manager).
# 2. Make it executable: chmod +x troubleshoot.sh
# 3. Run it from the project root: ./troubleshoot.sh
#TEST

set -e
set -o pipefail

# --- Pre-run check: Ensure script is run from the correct directory ---
if [ ! -f "daily_sync.py" ] || [ ! -d "db" ]; then
    echo "ERROR: This script must be run from the root of the project directory." >&2
    echo "Current directory is '$(pwd)'. Please 'cd' to the correct directory and re-run." >&2
    exit 1
fi

echo "### Starting Troubleshooter for daily_sync.py ###"
echo "This script will check the environment, configuration, and run the sync script manually."

# --- Activate Virtual Environment FIRST ---
echo ""
echo "--- Activating Python Virtual Environment ---"
if [ -d "venv" ]; then
    echo "Activating virtual environment from 'venv' directory..."
    source venv/bin/activate
else
    echo "ERROR: Python virtual environment 'venv' not found." >&2
    echo "Please ensure the setup process (user_data.sh) has completed successfully." >&2
    exit 1
fi

# --- Basic Environment Checks ---
echo ""
echo "--- 1. Basic Environment Info (within venv) ---"
echo "Current User: $(whoami)"
echo "Current Directory: $(pwd)"
echo "Python version: $(python --version 2>&1)"
echo "Path to Python executable: $(which python)"
if [ -f "requirements.txt" ]; then
    echo "Checking installed packages against requirements.txt..."
    pip check
else
    echo "requirements.txt not found, listing all packages:"
    pip list
fi


# --- File & Permission Checks ---
echo ""
echo "--- 2. File and Permission Checks ---"
echo "Listing key files and permissions..."
ls -la daily_sync.py .env db/cities.json

if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found!"
    exit 1
fi
if [ ! -f "db/cities.json" ]; then
    echo "ERROR: db/cities.json not found!"
    exit 1
fi


# --- Configuration Checks ---
echo ""
echo "--- 3. Configuration Checks ---"
echo "Crontab for ec2-user:"
sudo crontab -u ec2-user -l | { grep 'daily_sync.py' || echo "No cron job found for daily_sync.py"; }
echo ""
echo "Checking .env file (sensitive values are redacted)..."
# Redact sensitive info for display
sed -e 's/admin_password=.*/admin_password=REDACTED/' \
    -e 's/VERASET_API_KEY=.*/VERASET_API_KEY=REDACTED/' \
    -e 's/AWS_SECRET_ACCESS_KEY=.*/AWS_SECRET_ACCESS_KEY=REDACTED/' \
    .env


# --- Manual Script Execution ---
echo ""
echo "--- 4. Manual Execution of daily_sync.py ---"
echo "Attempting to run the script with the same environment as cron..."
echo "This will use yesterday's date for the sync."

# The venv is already activated. The python script will load .env itself.
# We do not `source .env` here because it can fail if values contain special characters.
# The python script handles this safely using the `python-dotenv` library.

echo "Running: python daily_sync.py"
python daily_sync.py

if [ $? -eq 0 ]; then
    echo "SUCCESS: daily_sync.py executed without errors."
else
    echo "ERROR: daily_sync.py failed with exit code $?."
fi

echo ""
echo "### Troubleshooting Complete ###"
echo "Review the output above for errors or warnings."
echo "Key things to check:"
echo "- Are all files present with correct permissions?"
echo "- Is the crontab entry correct?"
echo "- Does the .env file have the correct (non-quoted) values?"
echo "- Did the manual execution show any Python errors?" 