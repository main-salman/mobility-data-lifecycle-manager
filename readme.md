# Mobility Data Sync System (EC2 + Flask)

## Overview
This system automates the daily download and sync of Veraset mobility data for a configurable list of cities, using a simple password-protected Flask web UI on a single EC2 instance.

<img width="1154" height="1256" alt="image" src="https://github.com/user-attachments/assets/a75c9375-e99b-4f78-b3b9-fe7caad5d047" />

<img width="1107" height="1257" alt="image" src="https://github.com/user-attachments/assets/6bf5b369-d383-4775-8a68-f6440923812b" />

<img width="1133" height="999" alt="image" src="https://github.com/user-attachments/assets/6449778f-2d8d-4504-a188-e8b6c315aefd" />

<img width="1133" height="447" alt="image" src="https://github.com/user-attachments/assets/ef4da5fd-22bc-491d-be5e-abd7a4b0a518" />


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
- Only the 30 most recent local backups are kept; older backups are automatically deleted.
- **Additionally, every time cities.json is updated, a timestamped backup is uploaded to S3.**
  - The S3 bucket and folder for these backups are configurable via the `.env` file:
    - `CITIES_BACKUP_BUCKET` — S3 bucket for cities.json backups (e.g., `qoli-mobile-ping-raw-dev`)
    - `S3_BUCKET` — S3 bucket for main data sync (e.g., `veraset-data-qoli-dev`)
  - Each backup is stored in the `cities-backup/` folder in the specified S3 bucket, with a unique timestamp in the filename.
- The `/db` folder is excluded from version control via `.gitignore`, so your city data and backups are never committed to git.

You do not need to manage these backups manually—this is handled automatically by the app. S3 backups provide additional durability and disaster recovery for your city list.

## Environment Variables for S3

Add the following to your `.env` (see `.env.example`):
```
S3_BUCKET=veraset-data-qoli-dev           # Main data sync bucket
CITIES_BACKUP_BUCKET=qoli-mobile-ping-raw-dev  # Bucket for cities.json backups
```

## New Features

- City boundary display: When adding or editing a city, the app can now show the administrative boundary of the city on the map (if available) using OpenStreetMap/Overpass API.
- New endpoint `/city_boundary` (GET): Returns the city boundary as GeoJSON for a given city, country, and optional state. Used by the frontend map.

## Requirements

- Add `geojson` to your Python environment:
  ```bash
  pip install geojson
  ```
- The city boundary feature uses the public Overpass API (https://overpass-api.de/). This service may be rate-limited or unavailable at times. If boundaries do not appear, try again later or check Overpass API status.

