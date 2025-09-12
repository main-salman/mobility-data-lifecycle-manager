# Mobility Data Lifecycle Manager

## 🌍 Overview
This system automates the collection, processing, and synchronization of Veraset mobility data for multiple cities worldwide. It provides a comprehensive Flask web interface for city management and data synchronization, with robust error handling, progress tracking, and automated recovery capabilities.

<img width="1154" height="1256" alt="image" src="https://github.com/user-attachments/assets/a75c9375-e99b-4f78-b3b9-fe7caad5d047" />

<img width="1107" height="1257" alt="image" src="https://github.com/user-attachments/assets/6bf5b369-d383-4775-8a68-f6440923812b" />

<img width="1133" height="999" alt="image" src="https://github.com/user-attachments/assets/6449778f-2d8d-4504-a188-e8b6c315aefd" />

<img width="1133" height="447" alt="image" src="https://github.com/user-attachments/assets/ef4da5fd-22bc-491d-be5e-abd7a4b0a518" />


---

## 🏗️ System Architecture

### Core Components
- **Flask Web Application** (`flask_app.py`) - Management interface with modern UI
- **Sync Logic Engine** (`sync_logic.py`) - Handles Veraset API interactions and S3 operations  
- **Daily Sync Scheduler** (`daily_sync.py`) - Automated daily data collection
- **Utilities Module** (`utils.py`) - Shared functions for city management and AWS operations
- **Orchestrator** (`orchestrator.py`) - Job coordination and workflow management

### Infrastructure
- **EC2 Instance** (Amazon Linux 2, t3.medium+) - Hosts the application
- **S3 Buckets** - Storage for mobility data with organized folder structure
- **IAM Roles** - Secure access to AWS services and Veraset platform
- **Terraform** (`main.tf`) - Infrastructure as Code deployment

---

## 🔄 Complete Data Flow Workflow

### 1. City Configuration
```
Flask UI → Add City → cities.json → S3 Backup
```

### 2. API Call Process  
```
sync_logic.py → Veraset API → Job Submission → Job Polling → S3 Download
```

#### Step-by-Step API Workflow:

**Step 1: Payload Construction** (`build_sync_payload()`)
```python
payload = {
    "date_range": {"from_date": "2024-06-01", "to_date": "2024-07-31"},
    "schema_type": "TRIPS",
    "geo_radius": [{
        "poi_id": "city_center",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "distance_in_meters": 10000
    }]
}
```

**Step 2: API Request** (`make_api_request()`)
```bash
POST https://platform.prd.veraset.tech/v1/movement/job/pings
Headers:
  Content-Type: application/json
  X-API-Key: your_veraset_api_key
Body: [payload from Step 1]
```

**Step 3: Job Polling** (`wait_for_job_completion()`)
```python
for attempt in range(200):  # 200 minutes max
    status = requests.get(f"https://platform.prd.veraset.tech/v1/job/{job_id}")
    
    if status["data"]["status"] == "SUCCESS":
        s3_location = status["data"]["s3_location"]
        break
    elif status["data"]["status"] in ["FAILED", "CANCELLED"]:
        raise Exception("Job failed")
    
    time.sleep(60)  # Wait 1 minute between polls
```

**Step 4: S3 Data Transfer** (`sync_data_to_bucket_chunked()`)
```bash
# 1. Assume Veraset access role
aws sts assume-role \
    --role-arn arn:aws:iam::123456789012:role/VerasetS3AccessRole \
    --role-session-name veraset-sync-session

# 2. Export temporary credentials  
export AWS_ACCESS_KEY_ID="ASIA..."
export AWS_SECRET_ACCESS_KEY="abc123..."
export AWS_SESSION_TOKEN="FwoGZXIvYXdzE..."

# 3. Sync data with AWS CLI
aws s3 sync \
    --copy-props none \
    --exclude "*" \
    --include "*.parquet" \
    s3://veraset-prd-platform-us-west-2/output/United_Nations/job_folder/ \
    s3://your-destination-bucket/data/country/state/city/
```

### 3. S3 Folder Structure
```
s3://your-destination-bucket/
├── data/
│   ├── canada/british_columbia/vancouver/
│   │   ├── date=2024-06-01/part-00001.snappy.parquet
│   │   ├── date=2024-06-02/part-00002.snappy.parquet
│   │   └── date=2024-06-03/...
│   ├── saudi_arabia/riyadh/riyadh/
│   │   ├── date=2024-06-01/...
│   │   └── date=2024-06-02/...
│   └── [other countries...]
```

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

## 🔐 AWS Permissions Setup

### IAM Role Configuration

#### EC2 Instance Role (`EC2MobilityWorkerRole`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject", 
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-destination-bucket",
        "arn:aws:s3:::your-destination-bucket/*",
        "arn:aws:s3:::veraset-prd-platform-us-west-2", 
        "arn:aws:s3:::veraset-prd-platform-us-west-2/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole", 
      "Resource": "arn:aws:iam::123456789012:role/VerasetS3AccessRole"
    }
  ]
}
```

#### Trust Relationship for EC2 Role
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
```

---

## 🔄 Detailed Technical Processes

### Veraset API Integration

**Available Endpoints:**
- `movement/job/pings` - Location ping data
- `movement/job/pings_by_device` - Device-specific pings  
- `movement/job/trips` - Trip trajectory data
- `work/job/cohort` - Work location analysis
- `work/job/aggregate` - Aggregated statistics

**Schema Types:**
- **FULL** - Complete dataset with all fields
- **TRIPS** - Trip-focused subset  
- **BASIC** - Essential fields only

### Job Processing Workflow

1. **API Request** (`make_api_request()`)
   ```python
   response = requests.post(
       "https://platform.prd.veraset.tech/v1/movement/job/pings",
       headers={"X-API-Key": api_key, "Content-Type": "application/json"},
       json=payload
   )
   job_id = response.json()["data"]["job_id"]
   ```

2. **Job Polling** (`wait_for_job_completion()`)
   - **Interval**: 60 seconds
   - **Max Duration**: 100 minutes  
   - **Status Checks**: SUBMITTED → RUNNING → SUCCESS/FAILED

3. **S3 Transfer** (`sync_data_to_bucket_chunked()`)
   ```bash
   # Assume role for Veraset S3 access
   aws sts assume-role --role-arn arn:aws:iam::123456789012:role/VerasetS3AccessRole
   
   # Sync parquet files
   aws s3 sync s3://veraset-source/job_output/ s3://your-bucket/data/country/state/city/
   ```

### Batch Processing Logic

**Large City Lists** (>200 cities)
```python
city_batches = chunk_cities(cities, chunk_size=200)  # Veraset API limit
for batch in city_batches:
    make_api_request(endpoint, cities=batch)
```

**Large Date Ranges** (>31 days)  
```python
date_chunks = split_date_range(from_date, to_date, max_days=31)  # Veraset API limit
for chunk_start, chunk_end in date_chunks:
    make_api_request(endpoint, date_range=(chunk_start, chunk_end))
```

---

## Using the App
- **Enhanced Cities Table:** Real-time search and sorting across all columns 
- **Add/Edit/Delete Cities:** Use the web UI to manage your city list with interactive maps
- **Manual Sync:** Trigger sync for any city and date range via the UI
- **Batch Operations:** Sync all cities simultaneously with progress tracking  
- **Missing Data Recovery:** Automated gap detection and recovery tools

---

## Setting Up Daily Sync (Cron)
Configure automated daily synchronization via the web UI at `/daily_sync_config` or manually:
```bash
# Cron job (managed automatically via Flask UI)
0 2 * * * cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && python daily_sync.py >> app.log 2>&1
```

### Daily Sync Configuration (`daily_sync.py`)
```python
# Environment variables control sync behavior
DAILY_SYNC_ENDPOINTS=movement/job/pings,work/job/cohort
DAILY_SYNC_ENDPOINT_CONFIGS={"movement/job/pings":{"enabled_schemas":["TRIPS","FULL"]}}

# S3 bucket mapping per endpoint+schema
S3_BUCKET_MOVEMENT_PINGS_TRIPS=your-trips-bucket
S3_BUCKET_MOVEMENT_PINGS_FULL=your-full-bucket
```

**Processing Logic:**
1. Load all cities from `db/cities.json`
2. Parse endpoint configurations from environment variables
3. Execute all endpoint+schema combinations in parallel using `ThreadPoolExecutor`
4. Each configuration calls `sync_all_cities_for_date_range()` with appropriate parameters
5. Log detailed results and error summary

---

## 🌐 Environment Variables Configuration

### Authentication & API Access
```bash
admin_user=your_admin_username
admin_password=your_secure_password  
VERASET_API_KEY=your_veraset_api_key
```

### AWS Configuration
```bash
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=abc123...
AWS_SESSION_DURATION=3600  # Role assumption duration in seconds
```

### S3 Bucket Mapping
```bash
# Schema-specific buckets for different data types
S3_BUCKET_MOVEMENT_PINGS_TRIPS=your-trips-bucket
S3_BUCKET_MOVEMENT_PINGS_FULL=your-full-bucket
S3_BUCKET_MOVEMENT_PINGS_BASIC=your-basic-bucket
S3_BUCKET_WORK_COHORT_TRIPS=your-cohort-bucket
CITIES_BACKUP_BUCKET=your-backup-bucket
```

### Daily Sync Settings
```bash
SYNC_TIME=02:00  # UTC time for daily sync
DAILY_SYNC_ENDPOINTS=movement/job/pings,work/job/cohort
DAILY_SYNC_ENDPOINT_CONFIGS={"movement/job/pings":{"enabled_schemas":["TRIPS"]}}
```

---

## 📊 Data Analysis & Monitoring Tools

### Missing Data Detection (`report_missing_dates.py`)
```bash
# Check data completeness across all cities
python3 report_missing_dates.py \
    --bucket your-destination-bucket \
    --from 2024-06-01 \
    --to 2025-07-31 \
    --cities-json db/cities.json

# Output: Console summary + CSV report in reports/ folder
```

### Automated Data Recovery (`download_missing_data.py`)
```bash
# Automatically download missing data for all cities
python3 download_missing_data.py

# Uses existing sync logic with:
# - Sequential city processing
# - Date range optimization  
# - Progress tracking and logging
# - Error handling and retry logic
```

### Monitoring & Logs
- **Application Logs**: `app.log` (auto-rotated at 10,000 lines)
- **Sync Progress**: Real-time via Flask UI `/sync_progress/<sync_id>`
- **Job History**: `/sync_jobs` shows last 30 days of operations
- **Download Progress**: Background job logging to `download_progress.log`

---

## Using the App
- **Enhanced Cities Table:** Real-time search and sorting across all columns with DataTables.js
- **City Selection:** Checkboxes for selecting specific cities with "Select All" functionality
- **Add/Edit/Delete Cities:** Interactive maps with polygon/radius AOI selection
- **Manual Sync:** Trigger sync for any individual city and date range with progress monitoring
- **Selective Sync:** Sync only selected cities using checkbox selection with live count display
- **Batch Operations:** Sync all cities simultaneously with detailed progress tracking
- **Missing Data Recovery:** Automated gap detection and targeted recovery tools
- **Boundary Upload:** Shapefile processing for custom city boundaries

---

## 🔧 Advanced Features & Error Handling

### Credential Management
```python
# Automatic credential refresh on expiration
def get_fresh_s3_client():
    session = boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-west-2'
    )
    return session.client('s3')

# Role assumption with configurable duration
AWS_SESSION_DURATION=3600  # 1 hour (configurable)
```

### Progress Tracking & Resume Capability
```python
# Save progress during long operations
save_sync_progress(sync_id, completed_files, total_files)

# Resume interrupted operations
progress = load_sync_progress(sync_id)
start_from = progress.get('completed_files', 0)
```

### Error Recovery Strategies
- **API Quota Exceeded**: Graceful termination with user notification
- **S3 Sync Failures**: Automatic retry with exponential backoff
- **Credential Expiration**: Automatic token refresh and retry
- **Job Timeouts**: Resume capability with progress preservation

### Cities Table Enhancement (DataTables.js)
```javascript
// Real-time search across all columns
$('#citySearch').on('keyup', function() {
    table.search(this.value).draw();
});

// Sortable columns with custom styling
columnDefs: [
    { "orderable": true, "targets": [0,1,2,3,4,5,6] },  // All data columns
    { "orderable": false, "targets": [7] }               // Actions column
]
```

---

## 🚨 Troubleshooting

### Common Issues

**Flask App Not Responding:**
```bash
# Check Flask app status
ps aux | grep flask_app.py

# Restart Flask app  
cd /home/ec2-user/mobility-data-lifecycle-manager
source venv/bin/activate
nohup python flask_app.py > flask_app.log 2>&1 &
```

**API Authentication Errors:**
```bash
# Verify Veraset API key
curl -H "X-API-Key: your_key" https://platform.prd.veraset.tech/v1/user/info

# Check environment variables
echo $VERASET_API_KEY
```

**S3 Access Denied:**
```bash
# Test S3 access
aws s3 ls s3://your-destination-bucket/

# Verify role assumption
aws sts assume-role --role-arn arn:aws:iam::123456789012:role/VerasetS3AccessRole
```

**Missing Data Issues:**
```bash
# Generate missing data report
python3 report_missing_dates.py --bucket your-bucket --from 2024-06-01 --to 2025-07-31

# Run targeted recovery
python3 download_missing_data.py
```

### Log Analysis
```bash
# Application logs
tail -f app.log

# Search for specific errors
grep -i "error\|failed" app.log | tail -20

# Monitor sync progress
grep "SYNC" app.log | tail -10
```

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

