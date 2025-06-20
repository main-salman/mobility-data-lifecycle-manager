import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_logic import sync_all_cities_for_date_range
from utils import load_cities

# Load .env first
load_dotenv()

# --- Clean Logging Setup (Python 3.7 compatible) ---
# Manually remove all handlers from the root logger before configuring new ones.
# This is the correct, backward-compatible way to prevent duplicate log entries.
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
# --- End Logging Setup ---

print("VERASET_API_KEY:", os.environ.get("VERASET_API_KEY"), flush=True)

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
    """Get configured endpoints and their settings from environment variables with detailed logging."""
    logging.info("--- Parsing Daily Sync Configuration ---")
    
    endpoints_str = os.getenv('DAILY_SYNC_ENDPOINTS', '')
    logging.info(f"Loaded DAILY_SYNC_ENDPOINTS: '{endpoints_str}'")
    if endpoints_str.startswith("'") and endpoints_str.endswith("'"):
        endpoints_str = endpoints_str[1:-1]
        logging.info(f"Stripped quotes, result: '{endpoints_str}'")
    
    configs_str = os.getenv('DAILY_SYNC_ENDPOINT_CONFIGS', '{}')
    logging.info(f"Loaded DAILY_SYNC_ENDPOINT_CONFIGS: '{configs_str}'")
    if configs_str.startswith("'") and configs_str.endswith("'"):
        configs_str = configs_str[1:-1]
        logging.info(f"Stripped quotes, result: '{configs_str}'")

    if not endpoints_str:
        logging.warning("DAILY_SYNC_ENDPOINTS is not set. No sync will be performed.")
        return {}
        
    endpoints = [e.strip() for e in endpoints_str.split(',')]
    
    try:
        endpoint_schema_map = json.loads(configs_str)
        logging.info(f"Successfully parsed JSON config: {endpoint_schema_map}")
    except json.JSONDecodeError as e:
        logging.error(f"FATAL: Could not parse DAILY_SYNC_ENDPOINT_CONFIGS. Invalid JSON. Error: {e}")
        return {}

    final_configs = {}
    for endpoint in endpoints:
        # Get the schemas configured for this specific endpoint from the JSON map
        schemas_for_endpoint = endpoint_schema_map.get(endpoint, {}).get('enabled_schemas', [])
        
        if not schemas_for_endpoint:
            logging.warning(f"No enabled schemas found for endpoint '{endpoint}' in config. Skipping.")
            continue
            
        logging.info(f"Found {len(schemas_for_endpoint)} enabled schemas for endpoint '{endpoint}': {schemas_for_endpoint}")

        for schema in schemas_for_endpoint:
            config_key = f"{endpoint}#{schema}"
            bucket_env_var = S3_BUCKET_MAPPING.get(config_key)
            
            bucket_name = os.getenv(bucket_env_var) if bucket_env_var else None

            # Fallback to the main S3_BUCKET if the specific one is not defined or is an empty string
            if not bucket_name:
                logging.warning(f"S3 bucket for '{config_key}' ('{bucket_env_var}') is not set or empty. Falling back to default S3_BUCKET.")
                bucket_name = os.getenv('S3_BUCKET')

            # Final check to ensure we have a bucket
            if not bucket_name:
                logging.error(f"No bucket found for '{config_key}'. Neither '{bucket_env_var}' nor 'S3_BUCKET' are set. Skipping this schema.")
                continue
                
            # Remove quotes from the final bucket name, just in case
            if bucket_name.startswith("'") and bucket_name.endswith("'"):
                bucket_name = bucket_name[1:-1]

            logging.info(f"Configuration for '{config_key}': bucket is '{bucket_name}'")
            final_configs[config_key] = {
                'schema_type': schema,
                'bucket': bucket_name
            }
            
    logging.info(f"--- Finished Parsing Config. Found {len(final_configs)} total configurations to run. ---")
    return final_configs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, help='End date (YYYY-MM-DD)')
    args = parser.parse_args()

    # Get endpoint configurations
    endpoint_configs = get_endpoint_configs()
    
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