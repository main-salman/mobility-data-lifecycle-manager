import os
import subprocess
import json
import boto3
import requests
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv
import time
from requests.exceptions import RequestException
import concurrent.futures

load_dotenv()

logger = logging.getLogger(__name__)

REGION = 'us-west-2'
S3_BUCKET = os.getenv('S3_BUCKET')
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')
API_ENDPOINT = "https://platform.prd.veraset.tech"
AWS_CLI = '/usr/local/bin/aws'

def get_veraset_api_key():
    return os.environ.get('VERASET_API_KEY')

def send_sns_notification(email, subject, message):
    sns = boto3.client('sns', region_name=REGION)
    if SNS_TOPIC_ARN:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    else:
        print(f"SNS notification to {email}: {subject}\\n{message}")

def build_sync_payload(cities, from_date, to_date, schema_type="FULL"):
    if hasattr(from_date, 'strftime'):
        from_date_str = from_date.strftime('%Y-%m-%d')
    else:
        from_date_str = str(from_date)
    if hasattr(to_date, 'strftime'):
        to_date_str = to_date.strftime('%Y-%m-%d')
    else:
        to_date_str = str(to_date)

    payload = {
        "date_range": {"from_date": from_date_str, "to_date": to_date_str},
        "schema_type": schema_type
    }
    
    geo_radius = []
    geo_json = []

    if not isinstance(cities, list):
        cities = [cities]

    for city in cities:
        poi_id_city = city['city'].lower().replace(' ', '_')
        if 'radius_meters' in city and city['radius_meters']:
            geo_radius.append({
                "poi_id": f"{poi_id_city}_center",
                "latitude": float(city['latitude']),
                "longitude": float(city['longitude']),
                "distance_in_meters": int(city['radius_meters'])
            })
        elif 'polygon_geojson' in city and city['polygon_geojson']:
            geo_json.append({
                "poi_id": f"{poi_id_city}_polygon",
                "geo_json": city['polygon_geojson']['geometry'] if 'geometry' in city['polygon_geojson'] else city['polygon_geojson']
            })

    if geo_radius:
        payload["geo_radius"] = geo_radius
    if geo_json:
        payload["geo_json"] = geo_json
        
    return payload

def make_api_request(endpoint, method="POST", data=None):
    # Normalize endpoint to avoid double /v1/
    endpoint = endpoint.lstrip('/')
    if endpoint.startswith('v1/'):
        endpoint = endpoint[3:]
    url = f"{API_ENDPOINT}/v1/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": get_veraset_api_key()
    }
    if method == "POST":
        logger.info(f"[API POST] Endpoint: {url}")
        logger.info(f"[API POST] Headers: {headers}")
        logger.info(f"[API POST] Payload: {json.dumps(data, indent=2)}")
    try:
        resp = requests.request(method, url, headers=headers, json=data)
        logger.info(f"[API POST] Response Status: {resp.status_code}")
        logger.info(f"[API POST] Response Text: {resp.text}")
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

def sync_data_to_bucket(city, date, s3_location, s3_bucket=None):
    source_bucket = "veraset-prd-platform-us-west-2"
    role_arn = "arn:aws:iam::651706782157:role/VerasetS3AccessRole"
    if not s3_bucket:
        raise ValueError("No S3 bucket specified. s3_bucket must be provided explicitly to sync_data_to_bucket.")
    
    country = city['country'].strip().lower().replace(' ', '_')
    state = city.get('state_province', '').strip().lower().replace(' ', '_')
    city_name = city['city'].strip().lower().replace(' ', '_')
    if state:
        dest_prefix = f"data/{country}/{state}/{city_name}"
    else:
        dest_prefix = f"data/{country}/{city_name}"

    source_path = s3_location['folder_path'].lstrip('/') if isinstance(s3_location, dict) else s3_location.lstrip('/')
    if not source_path.endswith('/'):
        source_path += '/'
    src_s3 = f"s3://{source_bucket}/{source_path}"
    dst_s3 = f"s3://{s3_bucket}/{dest_prefix}/"
    logger.info(f"[S3 SYNC] Source: {src_s3}")
    logger.info(f"[S3 SYNC] Destination: {dst_s3}")

    try:
        assume_role_cmd = [
            AWS_CLI, "sts", "assume-role",
            "--role-arn", role_arn,
            "--role-session-name", "veraset-sync-session",
            "--output", "json"
        ]
        result = subprocess.run(assume_role_cmd, capture_output=True, text=True, check=True)
        credentials = json.loads(result.stdout)["Credentials"]
    except Exception as e:
        logger.error(f"[S3 SYNC] Failed to assume Veraset S3 access role: {str(e)}\\n{getattr(e, 'stderr', '')}")
        return {"success": False, "error": f"Failed to assume Veraset S3 access role: {str(e)}\\n{getattr(e, 'stderr', '')}"}

    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
    env["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
    env["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
    
    sync_command = [
        AWS_CLI, "s3", "sync",
        "--copy-props", "none",
        "--no-progress",
        "--no-follow-symlinks",
        "--exclude", "*",
        "--include", "*.parquet",
        src_s3,
        dst_s3
    ]
    logger.info(f"[S3 SYNC] Running command: {' '.join(sync_command)}")
    try:
        sync_result = subprocess.run(sync_command, env=env, capture_output=True, text=True, check=True)
        copy_lines = [l for l in sync_result.stdout.splitlines() if l.startswith('copy:')]
        non_copy_lines = [l for l in sync_result.stdout.splitlines() if not l.startswith('copy:')]
        total_copies = len(copy_lines)
        summary_lines = []
        if total_copies > 10:
            summary_lines.extend(copy_lines[:5])
            summary_lines.append(f"... ({total_copies-10} copy lines omitted) ...")
            summary_lines.extend(copy_lines[-5:])
        else:
            summary_lines = copy_lines
        log_output = '\\n'.join(non_copy_lines + summary_lines)
        logger.info(f"[S3 SYNC] stdout (filtered):\\n{log_output}")
        logger.info(f"[S3 SYNC] stderr: {sync_result.stderr}")
        if total_copies == 0:
            logger.warning(f"[S3 SYNC] No files were copied from {src_s3} to {dst_s3}. Check if the source folder contains .parquet files.")
        
        try:
            log_path = os.path.join(os.path.dirname(__file__), 'app.log')
            with open(log_path, 'r') as f:
                lines = f.readlines()
            if len(lines) > 10000:
                with open(log_path + '.1', 'w') as f:
                    f.writelines(lines[:-10000])
                with open(log_path, 'w') as f:
                    f.writelines(lines[-10000:])
        except Exception as e:
            logger.warning(f"[S3 SYNC] Log rotation failed: {e}")
        return {"success": True, "dest_prefix": dest_prefix}
    except subprocess.CalledProcessError as e:
        logger.error(f"[S3 SYNC] S3 sync failed: {e.stderr or e.stdout or str(e)}")
        return {"success": False, "error": f"S3 sync failed: {e.stderr or e.stdout or str(e)}"}

# Helper to split a date range into 31-day chunks
def split_date_range(from_date, to_date, max_days=31):
    if isinstance(from_date, str):
        from_date = datetime.strptime(from_date, "%Y-%m-%d")
    if isinstance(to_date, str):
        to_date = datetime.strptime(to_date, "%Y-%m-%d")
    ranges = []
    current = from_date
    while current <= to_date:
        range_end = min(current + timedelta(days=max_days - 1), to_date)
        ranges.append((current, range_end))
        current = range_end + timedelta(days=1)
    return ranges

def sync_city_for_date(city, from_date, to_date=None, schema_type="FULL", api_endpoint="movement/job/pings", s3_bucket=None, max_workers=4):
    try:
        if to_date is None:
            to_date = from_date
        if not s3_bucket:
            raise ValueError("No S3 bucket specified. s3_bucket must be provided explicitly to sync_city_for_date.")

        # Split into 31-day chunks
        try:
            date_chunks = split_date_range(from_date, to_date, max_days=31)
            num_chunks = len(date_chunks)
            if num_chunks == 0:
                logger.error(f"[SYNC DEBUG] No date chunks generated for {city['city']} from {from_date} to {to_date}")
                return {"success": False, "error": "No date chunks generated"}
            if num_chunks > 20:
                logger.error(f"[SYNC DEBUG] Too many date chunks ({num_chunks}) for {city['city']} from {from_date} to {to_date}. Aborting to prevent runaway processing.")
                return {"success": False, "error": f"Too many date chunks ({num_chunks}), aborting."}
            first_chunk = date_chunks[0]
            last_chunk = date_chunks[-1]
            logger.debug(f"[SYNC DEBUG] {num_chunks} chunks to process for {city['city']}. First: {first_chunk[0].strftime('%Y-%m-%d')} to {first_chunk[1].strftime('%Y-%m-%d')}, Last: {last_chunk[0].strftime('%Y-%m-%d')} to {last_chunk[1].strftime('%Y-%m-%d')}")
        except Exception as e:
            logger.error(f"[SYNC DEBUG] Exception during chunking/logging: {e}", exc_info=True)
            return {"success": False, "error": f"Exception during chunking: {str(e)}"}

        all_results = []
        errors = []

        def process_chunk(chunk_start, chunk_end):
            try:
                payload = build_sync_payload(city, chunk_start, chunk_end, schema_type=schema_type)
                response = make_api_request(api_endpoint, data=payload)
                if not response or 'error' in response:
                    return {"error": response.get('error', 'No response from API')}
                request_id = response.get("request_id")
                job_id = response.get("data", {}).get("job_id")
                if not request_id or not job_id:
                    return {"error": f"No request_id or job_id in response: {response}"}
                status = wait_for_job_completion(job_id)
                if not status or 'error' in status:
                    return {"error": status.get('error', 'Unknown error during job status polling')}
                sync_result = sync_data_to_bucket(city, chunk_start, status.get('s3_location'), s3_bucket=s3_bucket)
                if not sync_result.get('success'):
                    return {"error": sync_result.get('error', 'Unknown error during S3 sync')}
                return {
                    "success": True,
                    "s3_location": status.get('s3_location'),
                    "dest_prefix": sync_result.get('dest_prefix'),
                    "date_range": (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d'))
                }
            except Exception as e:
                logger.error(f"[SYNC DEBUG] Exception in chunk {chunk_start} to {chunk_end}: {e}", exc_info=True)
                return {"error": f"Exception: {str(e)}"}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(process_chunk, chunk_start, chunk_end): (chunk_start, chunk_end)
                for chunk_start, chunk_end in date_chunks
            }
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_start, chunk_end = future_to_chunk[future]
                try:
                    result = future.result()
                    if result.get('success'):
                        all_results.append(result)
                    else:
                        errors.append(f"{chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}: {result.get('error')}")
                except Exception as e:
                    logger.error(f"[SYNC DEBUG] Exception retrieving future for chunk {chunk_start} to {chunk_end}: {e}", exc_info=True)
                    errors.append(f"{chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}: Exception: {str(e)}")
        logger.debug(f"[SYNC DEBUG] Finished processing {num_chunks} chunks for {city['city']}. Results: {len(all_results)}, Errors: {len(errors)}")
        if errors and not all_results:
            return {"success": False, "error": "; ".join(errors)}
        return {"success": True, "results": all_results, "errors": errors} if errors else {"success": True, "results": all_results}
    except Exception as e:
        logger.error(f"Error in sync_city_for_date for {city['city']}: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

def sync_all_cities_for_date_range(cities, from_date, to_date, schema_type, endpoint, s3_bucket):
    logger.info(f"[Sync All] Starting sync for {len(cities)} cities from {from_date} to {to_date} using endpoint {endpoint}")

    # Split into 31-day chunks
    date_chunks = split_date_range(from_date, to_date, max_days=31)
    all_results = []
    errors = []
    for chunk_start, chunk_end in date_chunks:
        payload = build_sync_payload(
            cities=cities,
            from_date=chunk_start,
            to_date=chunk_end,
            schema_type=schema_type
        )
        response = make_api_request(endpoint, data=payload)
        if not response or 'error' in response:
            errors.append(response.get('error', 'No response from API'))
            continue
        request_id = response.get("request_id")
        job_id = response.get("data", {}).get("job_id")
        if not request_id or not job_id:
            errors.append(f"No request_id or job_id in response: {response}")
            continue
        status = wait_for_job_completion(job_id)
        if not status or 'error' in status:
            errors.append(status.get('error', 'Unknown error during job status polling'))
            continue
        logger.info(f"[Sync All] Job {job_id} completed. Starting S3 sync for all cities.")
        chunk_errors = []
        for city in cities:
            sync_result = sync_data_to_bucket(city, chunk_start, status.get('s3_location'), s3_bucket=s3_bucket)
            if not sync_result.get('success'):
                chunk_errors.append(f"City {city['city']}: {sync_result.get('error', 'Unknown error during S3 sync')}")
        if chunk_errors:
            errors.extend(chunk_errors)
        all_results.append({
            "success": True,
            "s3_location": status.get('s3_location'),
            "date_range": (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d'))
        })
    if errors and not all_results:
        return {"success": False, "error": "; ".join(errors)}
    return {"success": True, "results": all_results, "errors": errors} if errors else {"success": True, "results": all_results} 