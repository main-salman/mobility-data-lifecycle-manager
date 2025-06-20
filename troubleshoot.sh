#!/bin/bash
# Troubleshooter for daily_sync.py on EC2

echo "### Starting Troubleshooter for daily_sync.py ###"
echo "This script will check the environment, configuration, and run the sync script manually."

# --- Basic Environment Checks ---
echo ""
echo "--- 1. Basic Environment Info ---"
echo "Current User: $(whoami)"
echo "Current Directory: $(pwd)"
echo "Python version: $(python --version 2>&1)"
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
fi
if [ ! -f "db/cities.json" ]; then
    echo "ERROR: db/cities.json not found!"
fi


# --- Configuration Checks ---
echo ""
echo "--- 3. Configuration Checks ---"
echo "Crontab for ec2-user:"
sudo crontab -u ec2-user -l
echo ""
echo "Checking .env file (sensitive values are redacted)..."
if [ -f ".env" ]; then
    # Redact sensitive info for display
    sed -e 's/admin_password=.*/admin_password=REDACTED/' \
        -e 's/VERASET_API_KEY=.*/VERASET_API_KEY=REDACTED/' \
        -e 's/AWS_SECRET_ACCESS_KEY=.*/AWS_SECRET_ACCESS_KEY=REDACTED/' \
        .env
else
    echo ".env file not found."
fi

# --- Manual Script Execution ---
echo ""
echo "--- 4. Manual Execution of daily_sync.py ---"
echo "Attempting to run the script with the same environment as cron..."
echo "This will use yesterday's date for the sync."

# Activate venv
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "WARNING: venv directory not found. Script may fail."
fi

# Run the python script
# The `set -a` command exports all variables created from this point onwards,
# so `python-dotenv` in the script can pick them up.
set -a
if [ -f ".env" ]; then
    source .env
fi
set +a

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