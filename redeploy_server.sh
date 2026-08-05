#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Step 1: Terraform (provision / replace EC2) ==="
terraform init -input=false
terraform apply

echo ""
echo "=== Step 2: Deploy application to EC2 ==="
"$SCRIPT_DIR/update_ec2.sh"

echo ""
echo "=== Step 3: Health check ==="
APP_URL="$(terraform output -raw app_url 2>/dev/null || echo "https://mobility.qolimpact.click")"
HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "${APP_URL%/}/login" || echo "000")"
if [ "$HTTP_CODE" = "200" ]; then
  echo "OK: ${APP_URL}/login returned HTTP $HTTP_CODE"
else
  echo "WARNING: ${APP_URL}/login returned HTTP $HTTP_CODE (expected 200)"
  echo "Check EC2 flask_app.log and nginx if the instance was just created (user_data may still be running)."
  exit 1
fi
