import os
import json
import threading
from datetime import datetime
from glob import glob
from dotenv import load_dotenv
import logging
import sys

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

def load_cities():
    if not os.path.exists(CITIES_FILE):
        return []
    with open(CITIES_FILE, 'r') as f:
        return json.load(f)

def save_cities(cities):
    backup_dir = os.path.dirname(CITIES_FILE) or '.'
    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')
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
            s3_key = f"cities-backup/cities.json.{timestamp}"
            s3_client.upload_file(CITIES_FILE, backup_bucket, s3_key)
            print(f"Backed up cities.json to s3://{backup_bucket}/{s3_key}")
        else:
            print("CITIES_BACKUP_BUCKET not set in .env, skipping S3 backup")
    except ImportError:
        print("boto3 not available, skipping S3 backup")
    except Exception as e:
        print(f"S3 backup failed: {e}") 