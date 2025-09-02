#!/usr/bin/env python3
"""
Download missing mobility data for cities based on missing dates CSV report.
Runs on EC2 instance using existing sync logic from the Flask application.
"""

import os
import sys
import csv
import json
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Import existing sync logic
from sync_logic import sync_city_for_date
from utils import load_cities, setup_logging

# Setup logging
setup_logging()
load_dotenv()

# Configuration - will be set to latest report automatically
MISSING_DATES_CSV = None  # Will find latest report file
API_ENDPOINT = 'movement/job/pings'
SCHEMA_TYPE = 'TRIPS'
S3_BUCKET = 'qoli-mobile-movement-ping-trips-dev'

# Cities to skip (as specified by user)
CITIES_TO_SKIP = {
    ('Thailand', 'Udon Thani', 'Udon Thani'),
    ('India', 'Odisha', 'Bhubaneswar'), 
    ('Australia', 'Queensland', 'Logan'),
    ('Ecuador', 'Pichincha', 'Quito'),
    ('Saudi Arabia', 'Al Madinah', 'Madinah'),
    ('Mexico', 'Querétaro', 'Querétaro'),
    ('Serbia', 'Nišava', 'Nis')
}

def normalize_name(name):
    """Normalize city/state/country names for comparison"""
    return name.strip().lower().replace(' ', '_').replace("'", '').replace('í', 'i').replace('é', 'e')

def find_city_in_db(cities_db, country, state, city):
    """Find matching city in the database"""
    for city_data in cities_db:
        db_country = normalize_name(city_data.get('country', ''))
        db_state = normalize_name(city_data.get('state_province', ''))
        db_city = normalize_name(city_data.get('city', ''))
        
        csv_country = normalize_name(country)
        csv_state = normalize_name(state)
        csv_city = normalize_name(city)
        
        if (db_country == csv_country and 
            db_state == csv_state and 
            db_city == csv_city):
            return city_data
    return None

def parse_date_ranges(ranges_str):
    """Parse JSON date ranges string into list of (start, end) tuples"""
    try:
        ranges = json.loads(ranges_str)
        date_ranges = []
        for range_pair in ranges:
            start_date = range_pair[0]
            end_date = range_pair[1]
            date_ranges.append((start_date, end_date))
        return date_ranges
    except Exception as e:
        logging.error(f"Error parsing date ranges '{ranges_str}': {e}")
        return []

def find_latest_missing_dates_csv():
    """Find the most recent missing dates CSV file"""
    import glob
    csv_files = glob.glob('reports/missing_dates_*.csv')
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getmtime)

def load_missing_dates_csv():
    """Load and parse the missing dates CSV"""
    global MISSING_DATES_CSV
    if MISSING_DATES_CSV is None:
        MISSING_DATES_CSV = find_latest_missing_dates_csv()
    
    cities_with_missing_data = []
    
    if not MISSING_DATES_CSV or not os.path.exists(MISSING_DATES_CSV):
        logging.error(f"Missing dates CSV not found: {MISSING_DATES_CSV}")
        return cities_with_missing_data
    
    with open(MISSING_DATES_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = row['country']
            state = row['state_province'] 
            city = row['city']
            missing_count = int(row['missing_count'])
            
            # Skip cities with no missing data
            if missing_count == 0:
                continue
                
            # Skip specified cities
            if (country, state, city) in CITIES_TO_SKIP:
                logging.info(f"Skipping {country}/{state}/{city} as requested")
                continue
            
            # Parse date ranges
            ranges_str = row['missing_ranges']
            date_ranges = parse_date_ranges(ranges_str)
            
            if date_ranges:
                cities_with_missing_data.append({
                    'country': country,
                    'state_province': state,
                    'city': city,
                    'missing_count': missing_count,
                    'date_ranges': date_ranges
                })
                logging.info(f"Added {country}/{state}/{city}: {missing_count} missing days, {len(date_ranges)} date ranges")
    
    return cities_with_missing_data

def download_city_data(city_data, db_city, date_ranges):
    """Download missing data for a city across all its date ranges"""
    country = city_data['country']
    state = city_data['state_province'] 
    city = city_data['city']
    
    logging.info(f"Starting download for {country}/{state}/{city} - {len(date_ranges)} date ranges")
    
    success_count = 0
    error_count = 0
    
    for i, (start_date, end_date) in enumerate(date_ranges):
        logging.info(f"  Range {i+1}/{len(date_ranges)}: {start_date} to {end_date}")
        
        try:
            result = sync_city_for_date(
                city=db_city,
                from_date=start_date,
                to_date=end_date,
                schema_type=SCHEMA_TYPE,
                api_endpoint=API_ENDPOINT,
                s3_bucket=S3_BUCKET
            )
            
            if result.get('success'):
                success_count += 1
                files_info = ""
                if 'results' in result:
                    total_files = sum(r.get('files_copied', 0) for r in result['results'])
                    files_info = f" ({total_files} files copied)"
                logging.info(f"  ✅ Range {i+1} completed successfully{files_info}")
            else:
                error_count += 1
                error_msg = result.get('error', 'Unknown error')
                logging.error(f"  ❌ Range {i+1} failed: {error_msg}")
                
        except Exception as e:
            error_count += 1
            logging.error(f"  ❌ Range {i+1} exception: {str(e)}")
        
        # Brief pause between ranges
        time.sleep(2)
    
    logging.info(f"Completed {country}/{state}/{city}: {success_count} successful, {error_count} failed")
    return success_count, error_count

def main():
    """Main execution function"""
    logging.info("=== Starting Missing Data Download Script ===")
    logging.info(f"API Endpoint: {API_ENDPOINT}")
    logging.info(f"Schema Type: {SCHEMA_TYPE}")
    logging.info(f"S3 Bucket: {S3_BUCKET}")
    
    # Load cities from database
    logging.info("Loading cities from database...")
    cities_db = load_cities()
    if not cities_db:
        logging.error("No cities found in database")
        return 1
    logging.info(f"Loaded {len(cities_db)} cities from database")
    
    # Load missing dates CSV
    logging.info(f"Loading missing dates from {MISSING_DATES_CSV}...")
    cities_with_missing = load_missing_dates_csv()
    if not cities_with_missing:
        logging.error("No cities with missing data found")
        return 1
    logging.info(f"Found {len(cities_with_missing)} cities with missing data")
    
    # Process each city
    total_success = 0
    total_errors = 0
    cities_processed = 0
    cities_not_found = 0
    
    for city_info in cities_with_missing:
        country = city_info['country']
        state = city_info['state_province']
        city = city_info['city']
        date_ranges = city_info['date_ranges']
        
        logging.info(f"\n{'='*60}")
        logging.info(f"Processing: {country} / {state} / {city}")
        logging.info(f"Missing: {city_info['missing_count']} days in {len(date_ranges)} ranges")
        
        # Find matching city in database
        db_city = find_city_in_db(cities_db, country, state, city)
        if not db_city:
            logging.warning(f"❌ City not found in database: {country}/{state}/{city}")
            cities_not_found += 1
            continue
        
        # Download data for this city
        success, errors = download_city_data(city_info, db_city, date_ranges)
        total_success += success
        total_errors += errors
        cities_processed += 1
        
        # Pause between cities to avoid overwhelming the API
        logging.info(f"Pausing 5 seconds before next city...")
        time.sleep(5)
    
    # Final summary
    logging.info(f"\n{'='*60}")
    logging.info("=== FINAL SUMMARY ===")
    logging.info(f"Cities processed: {cities_processed}")
    logging.info(f"Cities not found in DB: {cities_not_found}")
    logging.info(f"Total date ranges successful: {total_success}")
    logging.info(f"Total date ranges failed: {total_errors}")
    logging.info(f"Success rate: {total_success/(total_success+total_errors)*100:.1f}%" if (total_success + total_errors) > 0 else "N/A")
    logging.info("=== Script completed ===")
    
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Script failed with exception: {e}")
        sys.exit(1)
