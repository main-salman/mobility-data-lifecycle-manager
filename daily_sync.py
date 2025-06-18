import os
from dotenv import load_dotenv
load_dotenv()
print("VERASET_API_KEY:", os.environ.get("VERASET_API_KEY"), flush=True)
import sys
import json
from datetime import datetime, timedelta
from sync_logic import sync_city_for_date
import argparse
from utils import load_cities

CITIES_FILE = 'cities.json'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--schema-type', type=str, choices=['FULL', 'TRIPS', 'BASIC'], default='FULL', help='Schema type to use: FULL, TRIPS, or BASIC (default: FULL)')
    args = parser.parse_args()

    cities = load_cities()
    if not cities:
        print("No cities to sync.", flush=True)
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
    print(f"Syncing all cities for {from_date} to {to_date} with schema_type={args.schema_type}", flush=True)
    try:
        for city in cities:
            print(f"Syncing {city['city']} ({city['country']})...", flush=True)
            result = sync_city_for_date(city, from_date, to_date, schema_type=args.schema_type)
            print(json.dumps(result, indent=2), flush=True)
            if result and result.get('success', True):
                print(f"  Success: {city['city']} ({city['country']})", flush=True)
            else:
                print(f"  Failed: {city['city']} ({city['country']}) - {result.get('error', 'Unknown error') if result else 'Unknown error'}", flush=True)
    except Exception as e:
        print("Exception during sync:", e, flush=True)

if __name__ == "__main__":
    main() 