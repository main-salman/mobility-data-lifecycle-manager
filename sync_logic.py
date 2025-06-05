import os
import subprocess
import json
import boto3
import requests
from datetime import datetime
import logging

REGION = 'us-west-2'
SECRETS_NAME = 'veraset_api_key'  # Change if needed
S3_BUCKET = 'veraset-data-qoli-dev'
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')  # Optional: can be set per city/email
API_ENDPOINT = "https://platform.prd.veraset.tech"
VERASET_API_KEY = os.environ.get('VERASET_API_KEY')

# Helper to get secret from .env
def get_veraset_api_key():
    return os.environ['veraset_api_key']

# Helper to send SNS notification
def send_sns_notification(email, subject, message):
    sns = boto3.client('sns', region_name=REGION)
    # If using a topic, publish to topic; else, send email directly (if allowed)
    if SNS_TOPIC_ARN:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    else:
        # Fallback: print to console
        print(f"SNS notification to {email}: {subject}\n{message}")

# Helper to build payload as in scripts
def build_sync_payload(city, from_date, to_date):
    # Accepts from_date and to_date as string (YYYY-MM-DD) or datetime
    if hasattr(from_date, 'strftime'):
        from_date_str = from_date.strftime('%Y-%m-%d')
    else:
        from_date_str = str(from_date)
    if hasattr(to_date, 'strftime'):
        to_date_str = to_date.strftime('%Y-%m-%d')
    else:
        to_date_str = str(to_date)
    payload = {
        "date_range": {
            "from_date": from_date_str,
            "to_date": to_date_str
        },
        "schema_type": "FULL"
    }
    if 'radius_meters' in city:
        payload["geo_radius"] = [{
            "poi_id": f"{city['city'].lower()}_center",
            "latitude": float(city['latitude']),
            "longitude": float(city['longitude']),
            "distance_in_meters": float(city['radius_meters'])
        }]
    elif 'polygon_geojson' in city:
        # The API expects geo_json to be an array of objects with poi_id and geo_json
        payload["geo_json"] = [{
            "poi_id": f"{city['city'].lower()}_polygon",
            "geo_json": city['polygon_geojson']['geometry'] if 'geometry' in city['polygon_geojson'] else city['polygon_geojson']
        }]
    return payload

def make_api_request(endpoint, method="POST", data=None):
    url = f"{API_ENDPOINT}/v1/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": VERASET_API_KEY
    }
    if method == "POST":
        logging.info(f"[API POST] Endpoint: {url}")
        logging.info(f"[API POST] Headers: {headers}")
        logging.info(f"[API POST] Payload: {json.dumps(data, indent=2)}")
    try:
        resp = requests.request(method, url, headers=headers, json=data)
        logging.info(f"[API POST] Response Status: {resp.status_code}")
        logging.info(f"[API POST] Response Text: {resp.text}")
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"error": f"Non-JSON response: {resp.text}"}
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = resp.json()
        except Exception:
            error_detail = resp.text
        return {"error": f"API request error: {e}. Detail: {error_detail}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"API request error: {e}"}

def get_job_status(job_id):
    return make_api_request(f"job/{job_id}", method="GET")

def wait_for_job_completion(job_id, max_attempts=100, poll_interval=60, status_callback=None):
    import time
    for attempt in range(max_attempts):
        status = get_job_status(job_id)
        if status_callback:
            status_callback(status, attempt)
        if not status or 'error' in status:
            return {"error": f"Attempt {attempt+1}: No valid response from job status API. {status.get('error', '') if status else ''}"}
        if status["data"]["status"] == "SUCCESS":
            return {"success": True, "s3_location": status["data"]["s3_location"]}
        elif status["data"]["status"] == "FAILED":
            return {"error": f"Job failed: {status.get('error_message', 'Unknown error')}"}
        elif status["data"]["status"] == "CANCELLED":
            return {"error": "Job was cancelled"}
        time.sleep(poll_interval)
    return {"error": "Job timed out"}

def sync_data_to_bucket(city, date, s3_location):
    import json
    source_bucket = "veraset-prd-platform-us-west-2"
    role_arn = "arn:aws:iam::651706782157:role/VerasetS3AccessRole"
    # Build destination path: data/{country}/{state_province}/{city_name}/{date}
    country = city['country'].strip().lower().replace(' ', '_')
    state = city.get('state_province', '').strip().lower().replace(' ', '_')
    city_name = city['city'].strip().lower().replace(' ', '_')
    # Remove date_folder from destination path
    if state:
        dest_prefix = f"data/{country}/{state}/{city_name}"
    else:
        dest_prefix = f"data/{country}/{city_name}"
    # Remove leading slash if present
    source_path = s3_location['folder_path'].lstrip('/') if isinstance(s3_location, dict) else s3_location.lstrip('/')
    # 1. Assume role to get temp credentials
    try:
        assume_role_cmd = [
            "aws", "sts", "assume-role",
            "--role-arn", role_arn,
            "--role-session-name", "veraset-sync-session",
            "--output", "json"
        ]
        result = subprocess.run(assume_role_cmd, capture_output=True, text=True, check=True)
        credentials = json.loads(result.stdout)["Credentials"]
    except Exception as e:
        return {"success": False, "error": f"Failed to assume Veraset S3 access role: {str(e)}\n{getattr(e, 'stderr', '')}"}
    # 2. Set temp credentials in env for sync
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
        f"s3://{S3_BUCKET}/{dest_prefix}/"
    ]
    try:
        sync_result = subprocess.run(sync_command, env=env, capture_output=True, text=True, check=True)
        return {"success": True, "dest_prefix": dest_prefix}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"S3 sync failed: {e.stderr or e.stdout or str(e)}"}

def sync_city_for_date(city, from_date, to_date=None):
    try:
        if to_date is None:
            to_date = from_date
        payload = build_sync_payload(city, from_date, to_date)
        response = make_api_request("movement/job/pings", data=payload)
        if not response or 'error' in response:
            return {"success": False, "error": response.get('error', 'No response from API')}
        request_id = response.get("request_id")
        job_id = response.get("data", {}).get("job_id")
        if not request_id or not job_id:
            return {"success": False, "error": f"No request_id or job_id in response: {response}"}
        status = wait_for_job_completion(job_id)
        if not status or 'error' in status:
            return {"success": False, "error": status.get('error', 'Unknown error during job status polling')}
        # S3 sync step
        sync_result = sync_data_to_bucket(city, from_date, status.get('s3_location'))
        if not sync_result.get('success'):
            return {"success": False, "error": sync_result.get('error', 'Unknown error during S3 sync')}
        return {"success": True, "s3_location": status.get('s3_location'), "dest_prefix": sync_result.get('dest_prefix')}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Example usage (for integration with Flask):
# from sync_logic import sync_city_for_date
# result = sync_city_for_date(city, date) 