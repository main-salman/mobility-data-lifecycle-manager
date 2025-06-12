#!/bin/bash
set -e

# Print header
echo "==== CloudWatch Agent Troubleshooting ===="

# 1. Agent status
echo "\n[1] CloudWatch Agent Status:"
sudo systemctl status amazon-cloudwatch-agent || echo "CloudWatch agent not running."

# 2. Agent logs
echo "\n[2] Last 30 lines of CloudWatch Agent Log:"
sudo cat /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log | tail -30 || echo "No agent log found."

# 3. IAM Role (instance profile)
echo "\n[3] IAM Role (Instance Profile):"
curl -s http://169.254.169.254/latest/meta-data/iam/info || echo "Could not fetch IAM info."

# 4. Log file existence
echo "\n[4] Log File Existence and Last 10 Lines:"
for f in /var/log/messages /var/log/cloud-init.log; do
  echo "\nFile: $f"
  if [ -f "$f" ]; then
    ls -lh "$f"
    tail -10 "$f"
  else
    echo "File not found: $f"
  fi
done

# 5. CloudWatch Agent Config
echo "\n[5] CloudWatch Agent Config (/opt/aws/amazon-cloudwatch-agent/bin/config.json):"
cat /opt/aws/amazon-cloudwatch-agent/bin/config.json || echo "No config found."

# 6. Region
echo "\n[6] AWS Region:"
cat /etc/system-release || true
curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | grep region || echo "Could not fetch region."

# 7. Try restarting agent
echo "\n[7] Restarting CloudWatch Agent..."
sudo systemctl restart amazon-cloudwatch-agent && echo "Agent restarted."
sleep 5
echo "\n[8] Agent status after restart:"
sudo systemctl status amazon-cloudwatch-agent || echo "CloudWatch agent not running after restart."

echo "\n==== End of Troubleshooting ====" 