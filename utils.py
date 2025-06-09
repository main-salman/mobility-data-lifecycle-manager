import os
import json
import threading
from datetime import datetime
from glob import glob

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