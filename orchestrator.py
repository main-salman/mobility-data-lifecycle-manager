import json
import os
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Any
import uuid
from utils import load_cities

JOBS_FILE = 'jobs.json'

def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return []
    with open(JOBS_FILE, 'r') as f:
        return json.load(f)

def save_jobs(jobs):
    with open(JOBS_FILE, 'w') as f:
        json.dump(jobs, f, indent=2)

def lambda_handler(event, context):
    """
    Main Lambda handler for orchestrating mobility data collection
    """
    try:
        print(f"Starting mobility data orchestrator at {datetime.utcnow()}")
        
        # Check if this is a manual trigger with specific parameters
        manual_trigger = event.get('manual_trigger', False)
        target_date = event.get('target_date')  # Format: YYYY-MM-DD
        specific_cities = event.get('cities', [])  # List of city_ids
        backfill_days = event.get('backfill_days', 1)
        
        if manual_trigger:
            print(f"Manual trigger detected. Target date: {target_date}, Cities: {specific_cities}, Backfill days: {backfill_days}")
        
        # Get active cities from DynamoDB
        cities = get_active_cities(specific_cities if specific_cities else None)
        print(f"Found {len(cities)} active cities to process")
        
        if not cities:
            print("No active cities found")
            return {
                'statusCode': 200,
                'body': json.dumps('No active cities to process')
            }
        
        # Determine dates to process
        dates_to_process = get_dates_to_process(target_date, backfill_days)
        print(f"Processing dates: {dates_to_process}")
        
        # Create jobs for each city and date combination
        jobs = load_jobs()
        jobs_created = 0
        for city in cities:
            for process_date in dates_to_process:
                # Check if this job has already been completed
                if not should_process_job(city['city_id'], process_date):
                    print(f"Skipping {city['city_id']} for {process_date} - already processed")
                    continue
                
                # Create job message
                job_message = create_job_message(city, process_date)
                jobs.append(job_message)
                jobs_created += 1
        
        save_jobs(jobs)
        print(f"Created {jobs_created} jobs")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'jobs_created': jobs_created,
                'cities_count': len(cities),
                'dates_count': len(dates_to_process)
            })
        }
        
    except Exception as e:
        error_msg = f"Error in orchestrator: {str(e)}"
        print(error_msg)
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_msg})
        }

def get_active_cities(specific_cities: List[str] = None) -> List[Dict[str, Any]]:
    """
    Get active cities from DynamoDB
    """
    # For demo, load cities from a local file or hardcoded list
    cities = load_cities()  # Implement load_cities() as needed
    return cities

def get_dates_to_process(target_date: str = None, backfill_days: int = 1) -> List[str]:
    """
    Get list of dates to process
    """
    dates = []
    
    if target_date:
        # Use specific target date
        base_date = datetime.strptime(target_date, '%Y-%m-%d')
    else:
        # Use yesterday as base date
        base_date = datetime.utcnow() - timedelta(days=1)
    
    # Generate dates for backfill
    for i in range(backfill_days):
        process_date = base_date - timedelta(days=i)
        dates.append(process_date.strftime('%Y-%m-%d'))
    
    return dates

def should_process_job(city_id: str, process_date: str) -> bool:
    """
    Check if a job should be processed (not already completed)
    """
    # For demo, load jobs from a local file or hardcoded list
    jobs = load_jobs()
    
    try:
        date_city_key = f"{process_date}#{city_id}"
        # If we find a completed job, don't process again
        return not any(job['job_id'] == date_city_key for job in jobs)
        
    except Exception as e:
        print(f"Error checking job status for {city_id} on {process_date}: {e}")
        # If we can't check, err on the side of processing
        return True

def create_job_message(city: Dict[str, Any], process_date: str) -> Dict[str, Any]:
    """
    Create a job message for SQS
    """
    job_id = str(uuid.uuid4())
    job = {
        'job_id': job_id,
        'city_id': city['city_id'],
        'city_name': city.get('city_name', city.get('city', '')),
        'country': city['country'],
        'state_province': city.get('state_province', ''),
        'latitude': city['latitude'],
        'longitude': city['longitude'],
        'process_date': process_date,
        'created_at': datetime.utcnow().isoformat(),
        'retry_count': 0
    }
    if 'radius_meters' in city:
        job['radius_meters'] = float(city['radius_meters'])
    elif 'polygon_geojson' in city:
        job['polygon_geojson'] = city['polygon_geojson']
    return job

def get_notification_emails() -> List[str]:
    """
    Get notification email addresses from DynamoDB
    """
    # For demo, return a hardcoded list
    return ['salman.naqvi@gmail.com']