import os
import json
import threading
from datetime import datetime, timezone
from glob import glob
from dotenv import load_dotenv
import logging
import sys
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
import time

# Load environment variables
load_dotenv()

CITIES_FILE = os.path.join('db', 'cities.json')
cities_lock = threading.Lock()
_logging_configured = False

def setup_logging():
    """
    Sets up a centralized, idempotent logger.
    """
    global _logging_configured
    if _logging_configured:
        return

    # Get the root logger
    logger = logging.getLogger()
    
    # Clear any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Configure the logger to write ONLY to the app.log file.
    # The StreamHandler is removed to prevent duplicate logs when
    # the process output is redirected to the same file.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
        handlers=[
            logging.FileHandler("app.log")
        ]
    )
    _logging_configured = True

def refresh_aws_session():
    """Create a new boto3 session with fresh credentials"""
    return boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-west-2'
    )

def get_fresh_s3_client():
    """Get S3 client with fresh credentials"""
    session = refresh_aws_session()
    return session.client('s3')

def check_credentials_validity(s3_client=None, max_age_hours=1):
    """Check if current credentials will expire soon"""
    if s3_client is None:
        s3_client = get_fresh_s3_client()
    try:
        # Test with a simple operation
        s3_client.list_buckets()
        return True
    except (ClientError, NoCredentialsError, PartialCredentialsError) as e:
        # Check if it's an expired token error
        if isinstance(e, ClientError):
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['ExpiredToken', 'TokenRefreshRequired', 'InvalidToken']:
                return False
        return False
    except Exception as e:
        logging.warning(f"Credential validity check failed with unexpected error: {e}")
        return False

def s3_copy_with_retry(source_bucket, source_key, dest_bucket, dest_key, max_retries=3):
    """S3 copy with automatic credential refresh on token expiration"""
    s3_client = get_fresh_s3_client()
    
    for attempt in range(max_retries):
        try:
            copy_source = {'Bucket': source_bucket, 'Key': source_key}
            s3_client.copy_object(
                CopySource=copy_source,
                Bucket=dest_bucket,
                Key=dest_key
            )
            return {'success': True}
        except (ClientError, NoCredentialsError, PartialCredentialsError) as e:
            # Check if it's an expired token or credential error
            is_credential_error = False
            if isinstance(e, ClientError):
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code in ['ExpiredToken', 'TokenRefreshRequired', 'InvalidToken', 'SignatureDoesNotMatch']:
                    is_credential_error = True
            elif isinstance(e, (NoCredentialsError, PartialCredentialsError)):
                is_credential_error = True
            
            if is_credential_error:
                logging.warning(f"Credentials issue during S3 copy (attempt {attempt+1}). Refreshing...")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    s3_client = get_fresh_s3_client()  # Get fresh credentials
                else:
                    logging.error(f"Failed to copy after {max_retries} attempts: {e}")
                    return {'success': False, 'error': f'Credential issues after {max_retries} attempts'}
            else:
                # Re-raise if it's not a credential error
                raise
        except Exception as e:
            logging.error(f"Non-credential error during S3 copy: {e}")
            return {'success': False, 'error': str(e)}

def save_sync_progress(sync_id, completed_files, total_files, additional_data=None):
    """Save progress to allow resuming on failure"""
    progress_file = f"sync_progress_{sync_id}.json"
    progress_data = {
        'completed_files': completed_files,
        'total_files': total_files,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'sync_id': sync_id
    }
    if additional_data:
        progress_data.update(additional_data)
    
    try:
        with open(progress_file, 'w') as f:
            json.dump(progress_data, f, indent=2)
        logging.info(f"Saved sync progress: {completed_files}/{total_files} files completed")
    except Exception as e:
        logging.error(f"Failed to save sync progress: {e}")

def load_sync_progress(sync_id):
    """Load previous progress to resume sync"""
    progress_file = f"sync_progress_{sync_id}.json"
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            logging.info(f"Loaded sync progress: {progress.get('completed_files', 0)}/{progress.get('total_files', 0)} files completed")
            return progress
        except Exception as e:
            logging.error(f"Failed to load sync progress: {e}")
    return None

def cleanup_sync_progress(sync_id):
    """Clean up progress file on completion"""
    progress_file = f"sync_progress_{sync_id}.json"
    try:
        if os.path.exists(progress_file):
            os.remove(progress_file)
            logging.info(f"Cleaned up sync progress file for sync {sync_id}")
    except Exception as e:
        logging.error(f"Failed to clean up sync progress file: {e}")

def load_cities():
    if not os.path.exists(CITIES_FILE):
        return []
    with open(CITIES_FILE, 'r') as f:
        return json.load(f)

def save_cities(cities):
    backup_dir = os.path.dirname(CITIES_FILE) or '.'
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
    backup_file = os.path.join(backup_dir, f"cities.json.{timestamp}")
    # Backup current cities.json if it exists
    if os.path.exists(CITIES_FILE):
        import shutil
        shutil.copy2(CITIES_FILE, backup_file)
        # Prune old backups, keep only 30 most recent
        backups = sorted(glob(os.path.join(backup_dir, "cities.json.*")), reverse=True)
        old_backups = backups[30:]
        for old in old_backups:
            try:
                os.remove(old)
            except Exception as e:
                print(f"Could not remove old backup {old}: {e}")
    with cities_lock:
        with open(CITIES_FILE, 'w') as f:
            json.dump(cities, f, indent=2)
    # S3 backup
    try:
        import boto3
        backup_bucket = os.getenv('CITIES_BACKUP_BUCKET')
        if backup_bucket:
            s3_client = boto3.client('s3')
            
            # Upload timestamped backup to city_polygons/backup/
            backup_s3_key = f"city_polygons/backup/cities.json.{timestamp}"
            s3_client.upload_file(CITIES_FILE, backup_bucket, backup_s3_key)
            print(f"Backed up cities.json to s3://{backup_bucket}/{backup_s3_key}")
            
            # Upload latest copy to city_polygons/latest/ (overwrite each time)
            latest_s3_key = "city_polygons/latest/cities.json"
            s3_client.upload_file(CITIES_FILE, backup_bucket, latest_s3_key)
            print(f"Updated latest cities.json at s3://{backup_bucket}/{latest_s3_key}")
        else:
            print("CITIES_BACKUP_BUCKET not set in .env, skipping S3 backup")
    except ImportError:
        print("boto3 not available, skipping S3 backup")
    except Exception as e:
        print(f"S3 backup failed: {e}") 