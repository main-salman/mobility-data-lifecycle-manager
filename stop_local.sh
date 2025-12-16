#!/bin/bash
set -e

echo "Stopping Flask application..."

# 1. Kill any Flask app running on port 5050
if lsof -ti:5050 > /dev/null 2>&1; then
  PIDS=$(lsof -ti:5050)
  echo "Killing processes on port 5050: $PIDS"
  kill $PIDS
else
  echo "No process found on port 5050"
fi

# 2. Kill any python process running flask_app.py
PIDS=$(ps aux | grep '[f]lask_app.py' | awk '{print $2}')
if [ ! -z "$PIDS" ]; then
  echo "Killing flask_app.py processes: $PIDS"
  kill $PIDS
else
  echo "No flask_app.py processes found"
fi

# 3. Kill any gunicorn processes (if running)
PIDS=$(ps aux | grep '[g]unicorn' | awk '{print $2}')
if [ ! -z "$PIDS" ]; then
  echo "Killing gunicorn processes: $PIDS"
  kill $PIDS
else
  echo "No gunicorn processes found"
fi

# 4. Wait for port 5050 to be free
for i in {1..10}; do
  if lsof -ti:5050 > /dev/null 2>&1; then
    echo "Waiting for port 5050 to be free..."
    sleep 1
  else
    break
  fi
done

# 5. Verify port is free
if lsof -ti:5050 > /dev/null 2>&1; then
  echo "WARNING: Port 5050 is still in use. You may need to force kill:"
  echo "  kill -9 \$(lsof -ti:5050)"
  exit 1
else
  echo "✓ Application stopped successfully. Port 5050 is now free."
fi
