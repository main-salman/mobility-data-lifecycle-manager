# Mobility Data Sync System (EC2 + Flask)

## Overview
This system automates the daily download and sync of Veraset mobility data for a configurable list of cities, using a simple password-protected Flask web UI on a single EC2 instance.

---

## Prerequisites
- Amazon Linux 2 EC2 instance (t3.medium or larger recommended)
- SSH access with your `salman-dev.pem` key
- AWS account with permissions for DynamoDB, S3, SNS, and Secrets Manager
- The following files uploaded to your EC2 instance:
  - `setup_ec2.sh`
  - `flask_app.py`
  - `sync_logic.py`
  - `dynamodb_create_table.py`
  - `.env` (with admin_user and admin_password)

---

## Setup Steps

### 1. SSH into your EC2 instance
```
ssh -i salman-dev.pem ec2-user@<EC2_PUBLIC_IP>
```

### 2. Upload all project files
Use `scp` or `rsync` to upload the files listed above to your EC2 home directory.

### 3. Run the setup script
```
chmod +x setup_ec2.sh
./setup_ec2.sh
```
This will:
- Install all dependencies
- Set up Python environment
- Create the DynamoDB table
- Set up SNS topic and subscribe your email
- Set up Flask as a systemd service
- Create a daily sync script

### 4. Complete manual AWS Console steps
- **Secrets Manager:**
  - Go to AWS Console > Secrets Manager > Store a new secret
  - Type: Other type of secret
  - Key: `VERASET_API_KEY`, Value: `<your-api-key>`
  - Secret name: `veraset_api_key`
- **S3 Lifecycle:**
  - Go to S3 Console > `veraset-data-qoli-dev` > Management > Lifecycle rules
  - Add a rule to delete objects older than 7 days
- **SNS Email Confirmation:**
  - Check your email (`salman.naqvi@gmail.com`) and confirm the SNS subscription

---

## Accessing the Flask Web UI
1. On your local machine, run:
   ```
   ssh -i salman-dev.pem -L 5000:localhost:5000 ec2-user@<EC2_PUBLIC_IP>
   ```
2. Open [http://localhost:5000](http://localhost:5000) in your browser
3. Login with the credentials from your `.env` file

---

## Using the App
- **Add/Edit/Delete Cities:** Use the web UI to manage your city list (country, state/province, city, latitude, longitude, notification email)
- **Manual Sync:** Trigger a sync for any city and date via the UI
- **Notifications:** If a sync fails, you will receive an email notification

---

## Setting Up Daily Sync (Cron)
To automate daily syncs for all cities, add this to your crontab:
```
0 2 * * * cd /home/ec2-user && source venv/bin/activate && python daily_sync.py
```
This will sync all cities for the previous day at 2am UTC.

---

## Troubleshooting
- **Flask app not running?**
  - Check status: `sudo systemctl status flask_app.service`
  - View logs: `journalctl -u flask_app.service -e`
- **No data in S3?**
  - Check for errors in the Flask UI or logs
  - Ensure your Veraset API key is correct in Secrets Manager
- **No SNS emails?**
  - Make sure you confirmed the subscription in your email
- **DynamoDB table issues?**
  - Re-run `python dynamodb_create_table.py` if needed

---

## Contact
For help, contact: salman.naqvi@gmail.com