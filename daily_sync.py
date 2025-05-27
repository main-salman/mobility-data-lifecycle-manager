import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_logic import sync_city_for_date

# Load environment variables
load_dotenv()

CITIES_FILE = 'cities.json'

def load_cities():
    if not os.path.exists(CITIES_FILE):
        print(f"No {CITIES_FILE} found.")
        return []
    with open(CITIES_FILE, 'r') as f:
        return json.load(f)

def main():
    cities = load_cities()
    if not cities:
        print("No cities to sync.")
        return
    # Use yesterday in UTC
    date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"Syncing all cities for {date}")
    for city in cities:
        print(f"Syncing {city['city']} ({city['country']})...")
        result = sync_city_for_date(city, date)
        if result and result.get('success', True):
            print(f"  Success: {city['city']} ({city['country']})")
        else:
            print(f"  Failed: {city['city']} ({city['country']}) - {result.get('error', 'Unknown error') if result else 'Unknown error'}")

if __name__ == "__main__":
    main() 