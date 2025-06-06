import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_logic import sync_city_for_date
import argparse

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
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, help='End date (YYYY-MM-DD)')
    args = parser.parse_args()

    cities = load_cities()
    if not cities:
        print("No cities to sync.")
        return
    # Default: sync 7 days prior
    if args.from_date:
        from_date = args.from_date
    else:
        from_date = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    if args.to_date:
        to_date = args.to_date
    else:
        to_date = from_date
    print(f"Syncing all cities for {from_date} to {to_date}")
    for city in cities:
        print(f"Syncing {city['city']} ({city['country']})...")
        result = sync_city_for_date(city, from_date, to_date)
        if result and result.get('success', True):
            print(f"  Success: {city['city']} ({city['country']})")
        else:
            print(f"  Failed: {city['city']} ({city['country']}) - {result.get('error', 'Unknown error') if result else 'Unknown error'}")

if __name__ == "__main__":
    main() 