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

def get_endpoint_configs():
    """Get configured endpoints and their settings from environment variables"""
    endpoints = os.getenv('DAILY_SYNC_ENDPOINTS', 'movement/job/pings').split(',')
    endpoint_configs = json.loads(os.getenv('DAILY_SYNC_ENDPOINT_CONFIGS', '{}'))
    
    # Ensure default values for each endpoint
    configs = {}
    for endpoint in endpoints:
        endpoint = endpoint.strip()
        # Get enabled schemas for this endpoint
        enabled_schemas = endpoint_configs.get(endpoint, {}).get('enabled_schemas', ['FULL'])
        
        # Create a config for each enabled schema
        for schema in enabled_schemas:
            # Get the bucket for this endpoint+schema combination
            bucket_env_var = f"{endpoint}#{schema}"
            bucket = os.getenv(bucket_env_var, os.getenv('S3_BUCKET'))
            
            # Add to configs with endpoint#schema as key
            configs[f"{endpoint}#{schema}"] = {
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
    
    # Load cities
    cities = load_cities()
    
    # Set dates
    if args.from_date:
        from_date = args.from_date
        to_date = args.to_date if args.to_date else from_date
    else:
        yesterday = datetime.now() - timedelta(days=1)
        from_date = yesterday.strftime('%Y-%m-%d')
        to_date = from_date

    # Sync each city for each configured endpoint+schema combination
    for city in cities:
        for endpoint_schema, config in endpoint_configs.items():
            try:
                # Split endpoint and schema
                endpoint, schema = endpoint_schema.split('#')
                print(f"Syncing {city['city']} using {endpoint} (schema: {schema}, bucket: {config['bucket']})")
                sync_city_for_date(
                    city,
                    from_date,
                    to_date,
                    schema_type=config['schema_type'],
                    api_endpoint=endpoint,
                    s3_bucket=config['bucket']
                )
            except Exception as e:
                print(f"Error syncing {city['city']} with {endpoint_schema}: {str(e)}", file=sys.stderr)
                continue

if __name__ == '__main__':
    main() 