import requests
import time
import json
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configuration
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")
API_ENDPOINT = "https://platform.prd.veraset.tech"
API_KEY = os.getenv("VERASET_API_KEY")

# Toronto coordinates (approximate center)
TORONTO_COORDS = {
    "latitude": 43.6532,
    "longitude": -79.3832,
    "distance_in_meters": 50000  # 50km radius to cover Toronto
}

# Helper to generate date ranges (max 7 days per range)
def generate_date_ranges(start_date, end_date, max_days=7):
    ranges = []
    current = start_date
    while current <= end_date:
        range_end = min(current + timedelta(days=max_days - 1), end_date)
        ranges.append((current, range_end))
        current = range_end + timedelta(days=1)
    return ranges

# API request logic
def make_api_request(endpoint, method="POST", data=None):
    url = f"{API_ENDPOINT}/v1/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    try:
        response = requests.request(method, url, headers=headers, json=data)
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError:
            print(f"Non-JSON response from API: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        raise

def get_job_status(job_id):
    return make_api_request(f"job/{job_id}", method="GET")

def wait_for_job_completion(job_id, max_attempts=3):
    for attempt in range(max_attempts):
        status = get_job_status(job_id)
        if not status:
            print(f"Attempt {attempt+1}: No valid response from job status API.")
            time.sleep(30)
            continue
        if status["data"]["status"] == "SUCCESS":
            return status["data"]["s3_location"]
        elif status["data"]["status"] == "FAILED":
            raise Exception(f"Job failed: {status.get('error_message', 'Unknown error')}")
        elif status["data"]["status"] == "CANCELLED":
            raise Exception("Job was cancelled")
        print(f"Job status: {status['data']['status']} (attempt {attempt + 1}/{max_attempts})")
        time.sleep(30)
    raise Exception("Job timed out")

def sync_data_to_bucket(source_path, destination_bucket, folder_suffix):
    source_bucket = "veraset-prd-platform-us-west-2"
    role_arn = "arn:aws:iam::651706782157:role/VerasetS3AccessRole"
    try:
        print("Assuming Veraset S3 access role...")
        assume_role_cmd = [
            "aws", "sts", "assume-role",
            "--role-arn", role_arn,
            "--role-session-name", "veraset-sync-session",
            "--profile", "default",
            "--output", "json"
        ]
        result = subprocess.run(assume_role_cmd, capture_output=True, text=True, check=True)
        try:
            credentials = json.loads(result.stdout)["Credentials"]
        except Exception as e:
            print("Failed to parse assume-role output as JSON.")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise e
        env = os.environ.copy()
        env["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
        env["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
        env["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
        sync_command = [
            "aws", "s3", "sync",
            "--copy-props", "none",
            "--no-progress",
            "--no-follow-symlinks",
            "--exclude", "*",
            "--include", "*.parquet",
            f"s3://{source_bucket}/{source_path}",
            f"s3://{destination_bucket}/toronto_mobility_2025/{folder_suffix}/"
        ]
        print(f"Syncing data from s3://{source_bucket}/{source_path} to s3://{destination_bucket}/toronto_mobility_2025/{folder_suffix}/")
        subprocess.run(sync_command, env=env, check=True)
        print(f"Successfully synced data to {destination_bucket} ({folder_suffix})")
    except subprocess.CalledProcessError as e:
        print(f"Error syncing data: {e}")
        raise

def main():
    # Only fetch remaining February 2025 ranges (Feb 8-14, 15-21, 22-28)
    date_ranges = [
        (datetime(2025, 2, 8), datetime(2025, 2, 14)),
        (datetime(2025, 2, 15), datetime(2025, 2, 21)),
        (datetime(2025, 2, 22), datetime(2025, 2, 28)),
    ]
    for idx, (from_date, to_date) in enumerate(date_ranges, 1):
        print(f"\n=== Processing range {from_date.date()} to {to_date.date()} ===")
        payload = {
            "date_range": {
                "from_date": from_date.strftime("%Y-%m-%d"),
                "to_date": to_date.strftime("%Y-%m-%d")
            },
            "schema_type": "FULL",
            "geo_radius": [{
                "poi_id": "toronto_center",
                "latitude": TORONTO_COORDS["latitude"],
                "longitude": TORONTO_COORDS["longitude"],
                "distance_in_meters": TORONTO_COORDS["distance_in_meters"]
            }]
        }
        try:
            print("Submitting job request...")
            response = make_api_request("movement/job/pings", data=payload)
            request_id = response.get("request_id")
            if not request_id:
                raise Exception("No request_id received in response")
            job_id = response.get("data", {}).get("job_id")
            if not job_id:
                raise Exception("No job_id received in response")
            print(f"Request submitted successfully: Request ID: {request_id}, Job ID: {job_id}")
            print("Waiting for job completion...")
            s3_location = wait_for_job_completion(job_id)
            print(f"Job completed. Data location: {s3_location}")
            folder_suffix = f"{from_date.strftime('%Y-%m-%d')}_to_{to_date.strftime('%Y-%m-%d')}"
            print("Syncing data to our bucket...")
            sync_data_to_bucket(
                s3_location["folder_path"].lstrip("/"),
                "veraset-data-qoli-dev",
                folder_suffix
            )
            print(f"Range {from_date.date()} to {to_date.date()} completed successfully!\n")
        except Exception as e:
            print(f"Error processing range {from_date.date()} to {to_date.date()}: {str(e)}")
            continue
    print("All ranges processed.")

if __name__ == "__main__":
    main() 