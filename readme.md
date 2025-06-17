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

## Setup Steps (Recommended)

### 1. Provision Infrastructure with Terraform
Run Terraform to create the EC2 instance and all required AWS resources:
```sh
terraform init
terraform apply
```
Follow prompts and wait for completion. Note the public IP of the new instance from the Terraform output.

### 2. Update Instance Info in update_ec2.sh
Edit `update_ec2.sh` and set the correct `EC2_HOST` (public IP) and any other relevant variables to match your new instance.

### 3. Deploy Code to the Instance
Run the update script to push the latest code and dependencies:
```sh
./update_ec2.sh
```
This will:
- Pull the latest code from GitHub
- Ensure Python dependencies are installed
- Restart the Flask app

### 4. Access the Instance
- Use the public DNS or IP from Terraform output to access the web UI (e.g., https://mobility.qolimpact.click/)
- Or use SSH as needed:
  ```sh
  ssh -i MY-AWS-KEY.pem ec2-user@<EC2_PUBLIC_IP>
  ```

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

## Updating the App After Code Changes

1. **Push your code changes to GitHub:**
   ```sh
   git add .
   git commit -m "Describe your changes"
   git push origin main
   ```
2. **Update the EC2 instance:**
   ```sh
   ./update_ec2.sh
   ```
   This will pull the latest Python code and restart the Flask app. (For infrastructure changes, re-run Terraform as described above.)

## City Data Storage and Backups

All city data is stored in the `/db` folder:
- The main city list is in `/db/cities.json`.
- Every time you add, edit, or delete a city, the app automatically creates a timestamped backup (e.g., `cities.json.2024-06-10_14-30-00`) in the same `/db` folder.
- Only the 30 most recent backups are kept; older backups are automatically deleted.
- The `/db` folder is excluded from version control via `.gitignore`, so your city data and backups are never committed to git.

You do not need to manage these backups manually—this is handled automatically by the app.

## New Features

- City boundary display: When adding or editing a city, the app can now show the administrative boundary of the city on the map (if available) using OpenStreetMap/Overpass API.
- New endpoint `/city_boundary` (GET): Returns the city boundary as GeoJSON for a given city, country, and optional state. Used by the frontend map.

## Requirements

- Add `geojson` to your Python environment:
  ```bash
  pip install geojson
  ```
- The city boundary feature uses the public Overpass API (https://overpass-api.de/). This service may be rate-limited or unavailable at times. If boundaries do not appear, try again later or check Overpass API status.

