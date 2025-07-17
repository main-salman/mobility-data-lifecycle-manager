import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_logic import sync_all_cities_for_date_range
from utils import load_cities, setup_logging
import concurrent.futures

# Centralized logging setup
setup_logging()

# Load .env first
load_dotenv()

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
    parser = argparse.ArgumentParser(description='Run daily data sync for Veraset.')
    parser.add_argument('--date', help='Date to sync for in YYYY-MM-DD format. Defaults to 7 days ago.')
    args = parser.parse_args()

    sync_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    if args.date:
        sync_date = args.date

    from_date = sync_date
    to_date = sync_date
    
    logging.info(f"Starting daily sync for date range: {from_date} to {to_date}")

    cities = load_cities()
    if not cities:
        logging.error("No cities found in cities.json. Exiting.")
        return

    logging.info(f"Loaded {len(cities)} cities for sync")
    if len(cities) > 200:
        logging.info(f"Note: {len(cities)} cities will be automatically split into batches of 200 for API compliance")

    configs = get_endpoint_configs()

    # Parallel execution for all endpoint+schema configs
    results = {}
    errors = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(configs))) as executor:
        future_to_key = {}
        for config_key, config in configs.items():
            endpoint, schema = config_key.split('#')
            bucket = config['bucket']
            schema_type = config['schema_type']
            logging.info(f"Submitting batch sync for ALL {len(cities)} cities using {endpoint} (schema: {schema_type}, bucket: {bucket})")
            future = executor.submit(
                sync_all_cities_for_date_range,
                endpoint=endpoint,
                cities=cities,
                from_date=from_date,
                to_date=to_date,
                schema_type=schema_type,
                s3_bucket=bucket
            )
            future_to_key[future] = (endpoint, schema_type)
        
        for future in concurrent.futures.as_completed(future_to_key):
            endpoint, schema_type = future_to_key[future]
            try:
                result = future.result()
                results[(endpoint, schema_type)] = result
                if result.get('success'):
                    total_batches = result.get('total_batches', 0)
                    total_results = len(result.get('results', []))
                    logging.info(f"✓ SUCCESS: {endpoint} ({schema_type}) - Processed {total_batches} batches with {total_results} successful operations")
                    
                    # Log batch details if available
                    if 'results' in result:
                        for idx, batch_result in enumerate(result['results']):
                            if 'batch_info' in batch_result:
                                cities_count = len(batch_result.get('cities_results', []))
                                logging.info(f"  {batch_result['batch_info']}: {cities_count} cities synced successfully")
                else:
                    errors[(endpoint, schema_type)] = result.get('error', 'Unknown error')
                    logging.error(f"✗ FAILED: {endpoint} ({schema_type}) - {result.get('error', 'Unknown error')}")
            except Exception as exc:
                errors[(endpoint, schema_type)] = str(exc)
                logging.error(f"✗ EXCEPTION: {endpoint} ({schema_type}) - {exc}")
    
    # Final summary
    if errors:
        logging.error(f"Daily sync completed with {len(errors)} failures out of {len(configs)} total configurations:")
        for (endpoint, schema_type), error in errors.items():
            logging.error(f"  - {endpoint} ({schema_type}): {error}")
    else:
        logging.info(f"🎉 Daily sync completed successfully! All {len(configs)} configurations processed without errors.")
        
    # Log total cities processed
    total_cities_processed = 0
    for result in results.values():
        if result.get('success') and 'results' in result:
            for batch_result in result['results']:
                total_cities_processed += len(batch_result.get('cities_results', []))
    
    if total_cities_processed > 0:
        logging.info(f"Total city-endpoint-schema combinations processed: {total_cities_processed}")

if __name__ == '__main__':
    main() 