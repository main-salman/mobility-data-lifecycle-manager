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
from utils import (
    get_fresh_s3_client, s3_copy_with_retry, check_credentials_validity,
    save_sync_progress, load_sync_progress, cleanup_sync_progress,
    get_fresh_assumed_credentials, refresh_veraset_credentials_if_needed,
    clear_cached_credentials
)

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

def chunk_cities(cities, chunk_size=200):
    """Split cities into chunks of specified size (default 200 for Veraset API limit)"""
    chunks = []
    for i in range(0, len(cities), chunk_size):
        chunks.append(cities[i:i + chunk_size])
    return chunks

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

def wait_for_job_completion(job_id, max_attempts=200, poll_interval=60, status_callback=None):
    for attempt in range(max_attempts):
        # Refresh credentials periodically (every 50 minutes = ~50 attempts)
        if attempt > 0 and attempt % 50 == 0:
            logger.info(f"[JOB POLLING] After {attempt} attempts ({attempt} minutes), refreshing credentials...")
            if not refresh_veraset_credentials_if_needed():
                return {"error": f"Failed to refresh credentials during job polling (attempt {attempt+1})"}
        
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

def sync_data_to_bucket_chunked(city, date, s3_location, s3_bucket=None, sync_id=None, chunk_size=50):
    """Enhanced sync with chunked processing and credential refresh"""
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

    # Check for existing progress
    progress = load_sync_progress(sync_id) if sync_id else None
    start_from = progress.get('completed_files', 0) if progress else 0

    # Retry logic for expired credentials during S3 sync
    max_retries = 3
    for retry_attempt in range(max_retries):
        try:
            # Get fresh assumed role credentials with automatic renewal
            credentials = get_fresh_assumed_credentials(role_arn)
        except Exception as e:
            logger.error(f"[S3 SYNC] Failed to assume Veraset S3 access role: {str(e)}")
            return {"success": False, "error": f"Failed to assume Veraset S3 access role: {str(e)}"}

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
        logger.info(f"[S3 SYNC] Running command: {' '.join(sync_command)} (attempt {retry_attempt + 1}/{max_retries})")
        
        try:
            sync_result = subprocess.run(sync_command, env=env, capture_output=True, text=True, check=True)
            # If we get here, sync succeeded - break out of retry loop
            break
            
        except subprocess.CalledProcessError as e:
            # Check if it's an expired token error
            error_output = e.stderr or ""
            if "ExpiredToken" in error_output or "The provided token has expired" in error_output:
                logger.warning(f"[S3 SYNC] Credentials expired during sync (attempt {retry_attempt + 1}/{max_retries}), clearing cache and retrying...")
                clear_cached_credentials()  # Force fresh credentials on next attempt
                if retry_attempt == max_retries - 1:
                    logger.error(f"[S3 SYNC] Failed after {max_retries} attempts due to credential expiry")
                    return {"success": False, "error": f"S3 sync failed after {max_retries} attempts due to credential expiry"}
                continue  # Retry with fresh credentials
            else:
                # Non-credential error, don't retry
                logger.error(f"[S3 SYNC] Non-credential error: {e}")
                logger.error(f"[S3 SYNC] Command output: {error_output}")
                return {"success": False, "error": f"S3 sync failed: {error_output}"}
    
    # Process results (this code only runs if sync succeeded)
    try:
        copy_lines = [l for l in sync_result.stdout.splitlines() if l.startswith('copy:')]
        non_copy_lines = [l for l in sync_result.stdout.splitlines() if not l.startswith('copy:')]
        total_copies = len(copy_lines)
        
        # Save progress if sync_id provided
        if sync_id:
            save_sync_progress(sync_id, total_copies, total_copies, {
                'dest_prefix': dest_prefix,
                'city': city['city'],
                'status': 'completed'
            })
        
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
        
        # Clean up progress on successful completion
        if sync_id:
            cleanup_sync_progress(sync_id)
            
        return {"success": True, "dest_prefix": dest_prefix, "files_copied": total_copies}
    except subprocess.CalledProcessError as e:
        logger.error(f"[S3 SYNC] S3 sync failed: {e.stderr or e.stdout or str(e)}")
        return {"success": False, "error": f"S3 sync failed: {e.stderr or e.stdout or str(e)}", "can_resume": bool(sync_id)}

# Backward compatibility alias
def sync_data_to_bucket(city, date, s3_location, s3_bucket=None):
    """Backward compatibility wrapper"""
    return sync_data_to_bucket_chunked(city, date, s3_location, s3_bucket)

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
                sync_result = sync_data_to_bucket_chunked(city, chunk_start, status.get('s3_location'), s3_bucket=s3_bucket)
                if not sync_result.get('success'):
                    return {"error": sync_result.get('error', 'Unknown error during S3 sync')}
                return {
                    "success": True,
                    "s3_location": status.get('s3_location'),
                    "dest_prefix": sync_result.get('dest_prefix'),
                    "date_range": (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')),
                    "files_copied": sync_result.get('files_copied', 0)
                }
            except Exception as e:
                logger.error(f"[SYNC DEBUG] Exception in chunk {chunk_start} to {chunk_end}: {e}", exc_info=True)
                return {"error": f"Exception: {str(e)}"}

        # Sequential processing of chunks (prevents server overload)
        for chunk_start, chunk_end in date_chunks:
            result = process_chunk(chunk_start, chunk_end)
            if result.get('success'):
                all_results.append(result)
            else:
                errors.append(f"{chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}: {result.get('error')}")
        logger.debug(f"[SYNC DEBUG] Finished processing {num_chunks} chunks for {city['city']}. Results: {len(all_results)}, Errors: {len(errors)}")
        if errors and not all_results:
            return {"success": False, "error": "; ".join(errors)}
        return {"success": True, "results": all_results, "errors": errors} if errors else {"success": True, "results": all_results}
    except Exception as e:
        logger.error(f"Error in sync_city_for_date for {city['city']}: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

def sync_all_cities_for_date_range(cities, from_date, to_date, schema_type, endpoint, s3_bucket):
    """Enhanced sync_all with city batching for 200+ cities and improved error handling"""
    logger.info(f"[Sync All] Starting sync for {len(cities)} cities from {from_date} to {to_date} using endpoint {endpoint}")

    # Split cities into batches of 200 (Veraset API limit)
    city_batches = chunk_cities(cities, chunk_size=200)
    logger.info(f"[Sync All] Split {len(cities)} cities into {len(city_batches)} batches")

    # Split into 31-day chunks
    date_chunks = split_date_range(from_date, to_date, max_days=31)
    logger.info(f"[Sync All] Split date range into {len(date_chunks)} chunks")

    all_results = []
    errors = []
    
    total_batches = len(city_batches) * len(date_chunks)
    current_batch = 0

    for batch_idx, city_batch in enumerate(city_batches):
        logger.info(f"[Sync All] Processing city batch {batch_idx + 1}/{len(city_batches)} ({len(city_batch)} cities)")
        
        # Refresh credentials before processing each batch to ensure we have valid credentials
        if batch_idx > 0:  # Don't refresh on first batch, credentials should be fresh
            logger.info(f"[Sync All] Before processing batch {batch_idx + 1}, refreshing credentials...")
            if not refresh_veraset_credentials_if_needed():
                error_msg = f"Failed to refresh credentials before processing batch {batch_idx + 1}"
                logger.error(f"[Sync All] {error_msg}")
                errors.append(error_msg)
                continue  # Skip this batch but continue with others
        
        for chunk_idx, (chunk_start, chunk_end) in enumerate(date_chunks):
            current_batch += 1
            logger.info(f"[Sync All] Processing batch {current_batch}/{total_batches}: Cities {batch_idx + 1}/{len(city_batches)}, Date chunk {chunk_idx + 1}/{len(date_chunks)}")
            
            payload = build_sync_payload(
                cities=city_batch,
                from_date=chunk_start,
                to_date=chunk_end,
                schema_type=schema_type
            )
            
            # Make API request for this batch and date chunk
            response = make_api_request(endpoint, data=payload)
            if not response or 'error' in response:
                error_msg = f"Batch {batch_idx + 1}, Date chunk {chunk_idx + 1}: {response.get('error', 'No response from API')}"
                errors.append(error_msg)
                continue
                
            request_id = response.get("request_id")
            job_id = response.get("data", {}).get("job_id")
            if not request_id or not job_id:
                error_msg = f"Batch {batch_idx + 1}, Date chunk {chunk_idx + 1}: No request_id or job_id in response: {response}"
                errors.append(error_msg)
                continue
                
            # Wait for job completion
            status = wait_for_job_completion(job_id)
            if not status or 'error' in status:
                error_msg = f"Batch {batch_idx + 1}, Date chunk {chunk_idx + 1}: {status.get('error', 'Unknown error during job status polling')}"
                errors.append(error_msg)
                continue
                
            logger.info(f"[Sync All] Job {job_id} completed for batch {batch_idx + 1}, chunk {chunk_idx + 1}. Starting S3 sync for {len(city_batch)} cities.")
            
            # Sync S3 data for each city in this batch
            chunk_errors = []
            batch_results = []
            
            for city_idx, city in enumerate(city_batch):
                try:
                    # Create unique sync_id for each city sync
                    import uuid
                    city_sync_id = f"batch_{batch_idx}_chunk_{chunk_idx}_city_{city_idx}_{str(uuid.uuid4())[:8]}"
                    
                    sync_result = sync_data_to_bucket_chunked(
                        city=city, 
                        date=chunk_start, 
                        s3_location=status.get('s3_location'), 
                        s3_bucket=s3_bucket,
                        sync_id=city_sync_id
                    )
                    
                    if not sync_result.get('success'):
                        chunk_errors.append(f"City {city['city']}: {sync_result.get('error', 'Unknown error during S3 sync')}")
                    else:
                        batch_results.append({
                            'city': city['city'],
                            'dest_prefix': sync_result.get('dest_prefix'),
                            'files_copied': sync_result.get('files_copied', 0)
                        })
                        
                except Exception as e:
                    chunk_errors.append(f"City {city['city']}: Exception during S3 sync: {str(e)}")
                    logger.error(f"[Sync All] Exception syncing city {city['city']}: {e}", exc_info=True)
                    
            if chunk_errors:
                errors.extend([f"Batch {batch_idx + 1}, Date chunk {chunk_idx + 1}: {err}" for err in chunk_errors])
                
            all_results.append({
                "success": True,
                "s3_location": status.get('s3_location'),
                "date_range": (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')),
                "batch_info": f"Batch {batch_idx + 1}/{len(city_batches)} ({len(city_batch)} cities)",
                "cities_results": batch_results,
                "job_id": job_id
            })
            
            # Brief pause between batches to avoid overwhelming the system
            if current_batch < total_batches:
                time.sleep(2)
    
    logger.info(f"[Sync All] Completed processing {len(city_batches)} city batches across {len(date_chunks)} date chunks")
    logger.info(f"[Sync All] Results: {len(all_results)} successful batches, {len(errors)} errors")
    
    if errors and not all_results:
        return {"success": False, "error": "; ".join(errors)}
    return {"success": True, "results": all_results, "errors": errors, "total_batches": total_batches} if errors else {"success": True, "results": all_results, "total_batches": total_batches} 