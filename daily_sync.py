import os
from dotenv import load_dotenv
load_dotenv()
print("VERASET_API_KEY:", os.environ.get("VERASET_API_KEY"), flush=True)
import sys
import json
import logging
from datetime import datetime, timedelta
from sync_logic import sync_all_cities_for_date_range
import argparse
from utils import load_cities

# --- Set up logging ---
# A more robust setup to prevent duplicate handlers
log = logging.getLogger()
log.setLevel(logging.INFO)
if log.hasHandlers():
    log.handlers.clear()
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
# File Handler
fh = logging.FileHandler('app.log')
fh.setFormatter(formatter)
log.addHandler(fh)
# Console Handler
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(formatter)
log.addHandler(sh)
# --- End logging setup ---

CITIES_FILE = 'cities.json'

# This mapping should be consistent with flask_app.py
S3_BUCKET_MAPPING = {
    "movement/job/pings#FULL": "S3_BUCKET_MOVEMENT_PINGS_FULL",
    "movement/job/pings#TRIPS": "S3_BUCKET_MOVEMENT_PINGS_TRIPS",
    "movement/job/pings#BASIC": "S3_BUCKET_MOVEMENT_PINGS_BASIC",
    "movement/job/pings_by_device#FULL": "S3_BUCKET_MOVEMENT_PINGS_BY_DEVICE_FULL",
    "movement/job/pings_by_device#TRIPS": "S3_BUCKET_MOVEMENT_PINGS_BY_DEVICE_TRIPS",
    "movement/job/pings_by_device#BASIC": "S3_BUCKET_MOVEMENT_PINGS_BY_DEVICE_BASIC",
    "work/job/cohort#FULL": "S3_BUCKET_WORK_COHORT_FULL",
    "work/job/cohort#TRIPS": "S3_BUCKET_WORK_COHORT_TRIPS",
    "work/job/cohort#BASIC": "S3_BUCKET_WORK_COHORT_BASIC",
    "work/job/cohort_by_device#FULL": "S3_BUCKET_WORK_COHORT_BY_DEVICE_FULL",
    "work/job/cohort_by_device#TRIPS": "S3_BUCKET_WORK_COHORT_BY_DEVICE_TRIPS",
    "work/job/cohort_by_device#BASIC": "S3_BUCKET_WORK_COHORT_BY_DEVICE_BASIC",
    "movement/job/trips#FULL": "S3_BUCKET_MOVEMENT_TRIPS_FULL",
    "movement/job/trips#TRIPS": "S3_BUCKET_MOVEMENT_TRIPS_TRIPS",
    "movement/job/trips#BASIC": "S3_BUCKET_MOVEMENT_TRIPS_BASIC",
    "work/job/aggregate#FULL": "S3_BUCKET_WORK_AGGREGATE_FULL",
    "work/job/aggregate#TRIPS": "S3_BUCKET_WORK_AGGREGATE_TRIPS",
    "work/job/aggregate#BASIC": "S3_BUCKET_WORK_AGGREGATE_BASIC",
    "work/job/devices#FULL": "S3_BUCKET_WORK_DEVICES_FULL",
    "work/job/devices#TRIPS": "S3_BUCKET_WORK_DEVICES_TRIPS",
    "work/job/devices#BASIC": "S3_BUCKET_WORK_DEVICES_BASIC",
    "movement/job/pings_by_ip#FULL": "S3_BUCKET_MOVEMENT_PINGS_BY_IP_FULL",
    "movement/job/pings_by_ip#TRIPS": "S3_BUCKET_MOVEMENT_PINGS_BY_IP_TRIPS",
    "movement/job/pings_by_ip#BASIC": "S3_BUCKET_MOVEMENT_PINGS_BY_IP_BASIC",
    "/v1/home/job/devices#FULL": "S3_BUCKET_HOME_DEVICES_FULL",
    "/v1/home/job/devices#TRIPS": "S3_BUCKET_HOME_DEVICES_TRIPS",
    "/v1/home/job/devices#BASIC": "S3_BUCKET_HOME_DEVICES_BASIC",
    "/v1/home/job/aggregate#FULL": "S3_BUCKET_HOME_AGGREGATE_FULL",
    "/v1/home/job/aggregate#TRIPS": "S3_BUCKET_HOME_AGGREGATE_TRIPS",
    "/v1/home/job/aggregate#BASIC": "S3_BUCKET_HOME_AGGREGATE_BASIC",
    "/v1/home/job/cohort#FULL": "S3_BUCKET_HOME_COHORT_FULL",
    "/v1/home/job/cohort#TRIPS": "S3_BUCKET_HOME_COHORT_TRIPS",
    "/v1/home/job/cohort#BASIC": "S3_BUCKET_HOME_COHORT_BASIC"
}

def get_endpoint_configs():
    """Get configured endpoints and their settings from environment variables"""
    endpoints_str = os.getenv('DAILY_SYNC_ENDPOINTS', 'movement/job/pings')
    if endpoints_str.startswith("'") and endpoints_str.endswith("'"):
        endpoints_str = endpoints_str[1:-1]
    endpoints = endpoints_str.split(',')

    configs_str = os.getenv('DAILY_SYNC_ENDPOINT_CONFIGS', '{}')
    if configs_str.startswith("'") and configs_str.endswith("'"):
        configs_str = configs_str[1:-1]
    
    try:
        endpoint_configs = json.loads(configs_str)
    except json.JSONDecodeError as e:
        print(f"Error: Could not parse DAILY_SYNC_ENDPOINT_CONFIGS. Invalid JSON: {configs_str}", file=sys.stderr)
        print(f"JSONDecodeError: {e}", file=sys.stderr)
        return {}
    
    # Ensure default values for each endpoint
    configs = {}
    for endpoint in endpoints:
        endpoint = endpoint.strip()
        # Get enabled schemas for this endpoint
        enabled_schemas = endpoint_configs.get(endpoint, {}).get('enabled_schemas', ['FULL'])
        
        # Create a config for each enabled schema
        for schema in enabled_schemas:
            endpoint_schema_key = f"{endpoint}#{schema}"
            bucket_env_var = S3_BUCKET_MAPPING.get(endpoint_schema_key)
            
            bucket = None
            if bucket_env_var:
                bucket = os.getenv(bucket_env_var)

            # Fallback to default S3_BUCKET if specific one is not defined or empty
            if not bucket:
                bucket = os.getenv('S3_BUCKET')

            # Strip quotes from bucket name if they exist
            if bucket and bucket.startswith("'") and bucket.endswith("'"):
                bucket = bucket[1:-1]
            
            # Add to configs with endpoint#schema as key
            configs[endpoint_schema_key] = {
                'schema_type': schema,
                'bucket': bucket
            }
    
    return configs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, help='End date (YYYY-MM-DD)')
    args = parser.parse_args()

    # Get endpoint configurations
    endpoint_configs = get_endpoint_configs()
    
    # --- TEMPORARY DEBUGGING ---
    print(f"DEBUG: Loaded {len(endpoint_configs)} endpoint configurations:")
    import pprint
    pprint.pprint(endpoint_configs)
    # --- END TEMPORARY DEBUGGING ---
    
    # Load cities
    cities = load_cities()
    if not cities:
        logging.warning("No cities found in db/cities.json. Exiting.")
        return
    
    # Set dates
    if args.from_date:
        from_date = args.from_date
        to_date = args.to_date if args.to_date else from_date
    else:
        # Per UI note, sync for 7 days prior
        target_date = datetime.now() - timedelta(days=7)
        from_date = target_date.strftime('%Y-%m-%d')
        to_date = from_date

    logging.info(f"Starting daily sync for date range: {from_date} to {to_date}")

    # Sync all cities for each configured endpoint+schema combination
    for endpoint_schema, config in endpoint_configs.items():
        try:
            endpoint, schema = endpoint_schema.split('#')
            if not config.get('bucket'):
                logging.warning(f"Skipping {endpoint_schema} because S3 bucket is not configured.")
                continue

            logging.info(f"Starting batch sync for ALL cities using {endpoint} (schema: {schema}, bucket: {config['bucket']})")
            
            result = sync_all_cities_for_date_range(
                cities=cities,
                from_date=from_date,
                to_date=to_date,
                schema_type=config['schema_type'],
                api_endpoint=endpoint,
                s3_bucket=config['bucket']
            )
            
            if result.get('success'):
                logging.info(f"Batch sync successful for {endpoint_schema}")
            else:
                logging.error(f"Batch sync failed for {endpoint_schema}: {result.get('error')}")
                if result.get('details'):
                    for detail in result['details']:
                        logging.error(f"  - {detail}")

        except Exception as e:
            logging.error(f"Critical error during batch sync for {endpoint_schema}: {str(e)}", exc_info=True)
            continue
    
    logging.info("Daily sync process finished.")

if __name__ == '__main__':
    main() 