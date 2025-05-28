#!/bin/bash

# Get the latest EC2 instance public IP by Name tag
INSTANCE_NAME="mobility-manager"
KEY_FILE="salman-dev.pem"

INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
  --query 'Reservations[*].Instances[*].InstanceId' --output text | head -n1)

if [ -z "$INSTANCE_ID" ]; then
  echo "No running instance found with Name tag '$INSTANCE_NAME'."
  exit 1
fi

INSTANCE_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

if [ "$INSTANCE_IP" == "None" ] || [ -z "$INSTANCE_IP" ]; then
  echo "Instance $INSTANCE_ID does not have a public IP."
  exit 1
fi

echo "Testing instance at: $INSTANCE_IP"

# Test HTTP (port 80)
INSTANCE_URL="http://$INSTANCE_IP"
echo "Testing HTTP access to $INSTANCE_URL ..."
HTTP_STATUS=$(curl -s -o /tmp/instance_http_test.html -w "%{http_code}" "$INSTANCE_URL")
if [ "$HTTP_STATUS" == "200" ]; then
    echo "[HTTP:80] Success: Status 200"
    if grep -q 'Mobility Cities' /tmp/instance_http_test.html; then
        echo "[HTTP:80] Flask app appears to be running (found 'Mobility Cities')"
    else
        echo "[HTTP:80] Flask app may not be running or returned unexpected content."
    fi
else
    echo "[HTTP:80] Failed: Status $HTTP_STATUS"
fi

# Test HTTPS (port 443)
INSTANCE_URL_HTTPS="https://$INSTANCE_IP"
echo "Testing HTTPS access to $INSTANCE_URL_HTTPS ..."
HTTPS_STATUS=$(curl -k -s -o /tmp/instance_https_test.html -w "%{http_code}" "$INSTANCE_URL_HTTPS")
if [ "$HTTPS_STATUS" == "200" ]; then
    echo "[HTTPS:443] Success: Status 200"
    if grep -q 'Mobility Cities' /tmp/instance_https_test.html; then
        echo "[HTTPS:443] Flask app appears to be running (found 'Mobility Cities')"
    else
        echo "[HTTPS:443] Flask app may not be running or returned unexpected content."
    fi
else
    echo "[HTTPS:443] Failed: Status $HTTPS_STATUS"
fi

# Test HTTP (port 5050)
INSTANCE_URL_5050="http://$INSTANCE_IP:5050"
echo "Testing HTTP access to $INSTANCE_URL_5050 ..."
HTTP_5050_STATUS=$(curl -s -o /tmp/instance_http_5050_test.html -w "%{http_code}" "$INSTANCE_URL_5050")
if [ "$HTTP_5050_STATUS" == "200" ]; then
    echo "[HTTP:5050] Success: Status 200"
    if grep -q 'Mobility Cities' /tmp/instance_http_5050_test.html; then
        echo "[HTTP:5050] Flask app appears to be running (found 'Mobility Cities')"
    else
        echo "[HTTP:5050] Flask app may not be running or returned unexpected content."
    fi
else
    echo "[HTTP:5050] Failed: Status $HTTP_5050_STATUS"
fi

# Test HTTPS (port 5050)
INSTANCE_URL_HTTPS_5050="https://$INSTANCE_IP:5050"
echo "Testing HTTPS access to $INSTANCE_URL_HTTPS_5050 ..."
HTTPS_5050_STATUS=$(curl -k -s -o /tmp/instance_https_5050_test.html -w "%{http_code}" "$INSTANCE_URL_HTTPS_5050")
if [ "$HTTPS_5050_STATUS" == "200" ]; then
    echo "[HTTPS:5050] Success: Status 200"
    if grep -q 'Mobility Cities' /tmp/instance_https_5050_test.html; then
        echo "[HTTPS:5050] Flask app appears to be running (found 'Mobility Cities')"
    else
        echo "[HTTPS:5050] Flask app may not be running or returned unexpected content."
    fi
else
    echo "[HTTPS:5050] Failed: Status $HTTPS_5050_STATUS"
fi

rm -f /tmp/instance_http_test.html /tmp/instance_https_test.html /tmp/instance_http_5050_test.html /tmp/instance_https_5050_test.html

echo ""
echo "--- SSH TROUBLESHOOTING OUTPUT ---"
echo ""

ssh -i $KEY_FILE -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP '
  echo "==== ps aux | grep flask_app.py ===="
  ps aux | grep flask_app.py | grep -v grep
  echo "\n==== sudo netstat -tulnp | grep 5050 ===="
  sudo netstat -tulnp | grep 5050 || echo "No process listening on 5050"
  echo "\n==== tail -n 50 flask_app.log ===="
  tail -n 50 flask_app.log || echo "No flask_app.log found"
  echo "\n==== ls -l mobility-data-lifecycle-manager ===="
  ls -l mobility-data-lifecycle-manager || echo "mobility-data-lifecycle-manager directory not found"
  echo "\n==== Python version and pip list in venv ===="
  source mobility-data-lifecycle-manager/venv/bin/activate && python3 --version && pip list || echo "venv or Python not found"
  echo "\n==== Try to start Flask app manually ===="
  cd mobility-data-lifecycle-manager && source venv/bin/activate && python3 flask_app.py || echo "Manual Flask app start failed"
  echo "\n==== tail -n 50 /var/log/cloud-init-output.log ===="
  tail -n 50 /var/log/cloud-init-output.log || echo "No cloud-init-output.log found"
  echo "\n==== Check for /tmp/userdata-test.txt ===="
  if [ -f /tmp/userdata-test.txt ]; then
    echo "/tmp/userdata-test.txt exists. Contents:"; cat /tmp/userdata-test.txt
  else
    echo "/tmp/userdata-test.txt does NOT exist."
  fi
'

echo ""
echo "To SSH into the instance for further troubleshooting, run:"
echo "ssh -i $KEY_FILE ec2-user@$INSTANCE_IP"

# New diagnostics
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== find project directory anywhere ===="; sudo find / -name "mobility-data-lifecycle-manager" 2>/dev/null'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== find venv anywhere ===="; sudo find / -name "venv" 2>/dev/null'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== grep for errors, git, venv, clone in cloud-init-output.log ===="; sudo grep -i -E "error|fail|git|venv|clone" /var/log/cloud-init-output.log || echo "No matches"'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== first 60 lines of user-data.txt ===="; sudo head -n 60 /var/lib/cloud/instance/user-data.txt'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== last 60 lines of user-data.txt ===="; sudo tail -n 60 /var/lib/cloud/instance/user-data.txt'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'if [ -f /var/log/user_data.log ]; then echo "==== all echo lines from user_data.log ===="; sudo grep "\[user_data\]" /var/log/user_data.log; else echo "user_data.log not found"; fi'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== first 60 lines of user-data.txt (direct) ===="; sudo cat /var/lib/cloud/instance/user-data.txt | head -n 60'
ssh -i $KEY_FILE ec2-user@$INSTANCE_IP 'echo "==== last 60 lines of user-data.txt (direct) ===="; sudo cat /var/lib/cloud/instance/user-data.txt | tail -n 60' 