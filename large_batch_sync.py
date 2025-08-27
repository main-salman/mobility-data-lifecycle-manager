#!/usr/bin/env python3
"""
Enhanced script for processing large batch jobs (e.g., 51 cities for a full year)
with improved error handling, token refresh, and progress tracking.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sync_logic import sync_all_cities_for_date_range
from utils import load_cities, setup_logging
import time

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def validate_environment():
    """Validate required environment variables"""
    required_vars = [
        'VERASET_API_KEY',
        'S3_BUCKET_MOVEMENT_PINGS_FULL',
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False
    
    logger.info("Environment validation passed")
    return True

def split_cities_into_smaller_batches(cities, batch_size=25):
    """Split cities into smaller batches for better reliability"""
    batches = []
    for i in range(0, len(cities), batch_size):
        batches.append(cities[i:i + batch_size])
    return batches

def process_large_dataset(cities, from_date, to_date, endpoint="movement/job/pings", schema_type="FULL"):
    """Process large datasets with enhanced error handling and progress tracking"""
    
    logger.info(f"Starting large batch processing: {len(cities)} cities from {from_date} to {to_date}")
    
    # Get target S3 bucket
    s3_bucket = os.getenv('S3_BUCKET_MOVEMENT_PINGS_FULL')
    if not s3_bucket:
        logger.error("S3_BUCKET_MOVEMENT_PINGS_FULL not configured")
        return {"success": False, "error": "S3 bucket not configured"}
    
    # Split cities into smaller batches for better reliability
    city_batches = split_cities_into_smaller_batches(cities, batch_size=25)
    logger.info(f"Split {len(cities)} cities into {len(city_batches)} smaller batches of ~25 cities each")
    
    # Split date range into smaller chunks (1 week max)
    date_chunks = []
    current_date = datetime.strptime(from_date, "%Y-%m-%d") if isinstance(from_date, str) else from_date
    end_date = datetime.strptime(to_date, "%Y-%m-%d") if isinstance(to_date, str) else to_date
    
    while current_date <= end_date:
        chunk_end = min(current_date + timedelta(days=6), end_date)  # 7-day chunks
        date_chunks.append((current_date, chunk_end))
        current_date = chunk_end + timedelta(days=1)
    
    logger.info(f"Split date range into {len(date_chunks)} weekly chunks")
    
    total_operations = len(city_batches) * len(date_chunks)
    completed_operations = 0
    failed_operations = 0
    all_results = []
    
    # Process each combination of city batch and date chunk
    for batch_idx, city_batch in enumerate(city_batches):
        logger.info(f"\n=== Processing City Batch {batch_idx + 1}/{len(city_batches)} ({len(city_batch)} cities) ===")
        
        for chunk_idx, (chunk_start, chunk_end) in enumerate(date_chunks):
            operation_id = f"batch_{batch_idx + 1}_chunk_{chunk_idx + 1}"
            logger.info(f"\n--- Operation {operation_id}: {chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')} ---")
            
            start_time = time.time()
            
            try:
                # Process this specific combination
                result = sync_all_cities_for_date_range(
                    cities=city_batch,
                    from_date=chunk_start,
                    to_date=chunk_end,
                    schema_type=schema_type,
                    endpoint=endpoint,
                    s3_bucket=s3_bucket
                )
                
                elapsed_time = time.time() - start_time
                
                if result.get('success'):
                    completed_operations += 1
                    logger.info(f"✅ {operation_id} completed successfully in {elapsed_time:.1f}s")
                    
                    # Log detailed results
                    if 'results' in result:
                        total_files = sum(len(r.get('cities_results', [])) for r in result['results'])
                        logger.info(f"   {len(result['results'])} batches processed, {total_files} city syncs completed")
                    
                    all_results.append({
                        'operation_id': operation_id,
                        'city_batch_size': len(city_batch),
                        'date_range': (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')),
                        'elapsed_time': elapsed_time,
                        'result': result
                    })
                else:
                    failed_operations += 1
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"❌ {operation_id} failed in {elapsed_time:.1f}s: {error_msg}")
                
            except Exception as e:
                failed_operations += 1
                elapsed_time = time.time() - start_time
                logger.error(f"❌ {operation_id} failed with exception in {elapsed_time:.1f}s: {str(e)}", exc_info=True)
            
            # Progress update
            total_completed = completed_operations + failed_operations
            progress_pct = (total_completed / total_operations) * 100
            logger.info(f"Progress: {total_completed}/{total_operations} operations ({progress_pct:.1f}%) - {completed_operations} succeeded, {failed_operations} failed")
            
            # Brief pause between operations
            if total_completed < total_operations:
                logger.info("Pausing 10 seconds before next operation...")
                time.sleep(10)
    
    # Final summary
    logger.info(f"\n=== FINAL SUMMARY ===")
    logger.info(f"Total operations: {total_operations}")
    logger.info(f"Successful: {completed_operations}")
    logger.info(f"Failed: {failed_operations}")
    logger.info(f"Success rate: {(completed_operations/total_operations)*100:.1f}%")
    
    return {
        "success": completed_operations > 0,
        "total_operations": total_operations,
        "completed_operations": completed_operations,
        "failed_operations": failed_operations,
        "success_rate": (completed_operations/total_operations)*100,
        "results": all_results
    }

def main():
    parser = argparse.ArgumentParser(description='Process large batch data sync for Veraset')
    parser.add_argument('--from-date', required=True, help='Start date in YYYY-MM-DD format')
    parser.add_argument('--to-date', required=True, help='End date in YYYY-MM-DD format')
    parser.add_argument('--endpoint', default='movement/job/pings', help='API endpoint to use')
    parser.add_argument('--schema', default='FULL', help='Schema type (FULL, TRIPS, BASIC)')
    parser.add_argument('--dry-run', action='store_true', help='Print configuration without executing')
    
    args = parser.parse_args()
    
    logger.info("=== Large Batch Sync Starting ===")
    logger.info(f"Date range: {args.from_date} to {args.to_date}")
    logger.info(f"Endpoint: {args.endpoint}")
    logger.info(f"Schema: {args.schema}")
    
    # Validate environment
    if not validate_environment():
        sys.exit(1)
    
    # Load cities
    cities = load_cities()
    if not cities:
        logger.error("No cities found in cities.json")
        sys.exit(1)
    
    logger.info(f"Loaded {len(cities)} cities for processing")
    
    if args.dry_run:
        logger.info("DRY RUN MODE - Configuration validated, would process:")
        logger.info(f"  - {len(cities)} cities")
        logger.info(f"  - Date range: {args.from_date} to {args.to_date}")
        logger.info(f"  - Endpoint: {args.endpoint}")
        logger.info(f"  - Schema: {args.schema}")
        return
    
    # Process the large dataset
    result = process_large_dataset(
        cities=cities,
        from_date=args.from_date,
        to_date=args.to_date,
        endpoint=args.endpoint,
        schema_type=args.schema
    )
    
    if result['success']:
        logger.info("🎉 Large batch processing completed with some successes!")
        sys.exit(0)
    else:
        logger.error("💥 Large batch processing failed completely")
        sys.exit(1)

if __name__ == '__main__':
    main()