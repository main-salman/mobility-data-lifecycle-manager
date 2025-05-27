#!/bin/bash
set -e

# 1. Check for Python 3.9+
PYTHON_BIN=$(which python3 || which python)
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.9+ is required. Please install Python 3.9 or newer."
  exit 1
fi
PYTHON_VERSION=$($PYTHON_BIN -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')
PYTHON_MAJOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
  echo "Python 3.9+ is required. Found $PYTHON_VERSION."
  exit 1
fi

# 2. Set up Python virtual environment
if [ ! -d "venv" ]; then
  $PYTHON_BIN -m venv venv
fi
source venv/bin/activate

# 3. Install Python requirements
pip install --upgrade pip
pip install flask boto3 python-dotenv requests gunicorn

# 4. Check for .env, or create a template
if [ ! -f ".env" ]; then
  echo "admin_user=your_email@example.com" > .env
  echo "admin_password=YourPassword123" >> .env
  echo "# SNS_TOPIC_ARN=arn:aws:sns:us-west-2:123456789012:your-topic" >> .env
  echo ".env file created. Please edit it with your credentials."
fi

# 6. Kill any previous Flask app running on port 5000 or as flask_app.py
if lsof -ti:5050 > /dev/null; then
  echo "Killing previous Flask app on port 5050..."
  kill $(lsof -ti:5050)
fi
# Also kill any python process running flask_app.py
PIDS=$(ps aux | grep '[f]lask_app.py' | awk '{print $2}')
if [ ! -z "$PIDS" ]; then
  echo "Killing previous flask_app.py processes: $PIDS"
  kill $PIDS
fi
# Wait for port 5050 to be free
for i in {1..10}; do
  if lsof -ti:5050 > /dev/null; then
    echo "Waiting for port 5050 to be free..."
    sleep 1
  else
    break
  fi
done

# 7. Start Flask app
nohup python flask_app.py > flask_app.log 2>&1 &
sleep 2
if ! lsof -i:5050 > /dev/null; then
  echo "ERROR: Flask app did not start successfully. Check flask_app.log for details."
  tail -n 20 flask_app.log
  exit 1
fi

# 8. Print instructions
cat <<EOM

---
LOCAL SETUP COMPLETE!

- Flask app is running in the background on http://localhost:5050
- To view logs: tail -f flask_app.log
- To stop the app: kill \$(lsof -ti:5050)
- Login with credentials from your .env file
- Add/edit/delete cities and test manual syncs

If you want to use local DynamoDB or mock AWS, see README.md for advanced options.
---
EOM 