# Mobility Data Sync System (EC2 + Flask)

## Overview
This system automates the daily download and sync of Veraset mobility data for a configurable list of cities, using a simple password-protected Flask web UI on a single EC2 instance.


<img width="641" alt="image" src="https://github.com/user-attachments/assets/28d3d5bf-39b8-4d91-b633-29620a4a1d3d" />

<img width="520" alt="image" src="https://github.com/user-attachments/assets/0646bbcf-c593-4856-8bd7-d2f74fcd8145" />

<img width="720" alt="image" src="https://github.com/user-attachments/assets/7ced6a39-f9c3-49ac-9973-abc4a6c3677a" />

<img width="839" alt="image" src="https://github.com/user-attachments/assets/b7a83cf4-7342-4cf0-a210-735178843f72" />


---

## Prerequisites
- Amazon Linux 2 EC2 instance (t3.medium or larger recommended)
- SSH access with your `MY-AWS-KEY.pem` key
- AWS account with permissions for DynamoDB, S3, SNS, and Secrets Manager
- The following files uploaded to your EC2 instance:
  - `setup_ec2.sh`
  - `flask_app.py`
  - `sync_logic.py`
  - `.env` (see example)

---

## Setup Steps

### 1. SSH into your EC2 instance
```
ssh -i MY-AWS-KEY.pem ec2-user@<EC2_PUBLIC_IP>
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

## Updating the App After a GitHub Repo Update

To update the app on your EC2 instance after changes are pushed to the GitHub repository:

1. **SSH into your EC2 instance:**
   ```sh
   ssh -i salman-dev.pem ec2-user@<EC2_PUBLIC_IP>
   ```

2. **Navigate to the project directory:**
   ```sh
   cd ~/mobility-data-lifecycle-manager
   ```

3. **Pull the latest changes from GitHub:**
   ```sh
   git pull origin main
   ```

4. **(Optional) Update Python dependencies:**
   If `requirements.txt` has changed:
   ```sh
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   deactivate
   ```

5. **Restart the Flask app:**
   If running with a process manager (e.g., systemd, supervisor, or gunicorn), restart the service. If running manually, stop and re-run the app:
   ```sh
   # If running in the background, find and kill the process:
   pkill -f flask_app.py
   # Then restart:
   source venv/bin/activate
   python flask_app.py &
   ```

6. **Check the logs:**
   ```sh
   tail -f app.log
   ```

**Note:** If you have made changes to user_data.sh or deployment scripts, you may need to re-run those steps or re-provision the instance.

