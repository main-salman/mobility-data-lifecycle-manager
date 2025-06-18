import os
import json
import threading
from datetime import datetime
from glob import glob
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CITIES_FILE = os.path.join('db', 'cities.json')
cities_lock = threading.Lock()

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