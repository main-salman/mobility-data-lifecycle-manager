#!/usr/bin/env python3

import json
import boto3
import requests
import time
import subprocess
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import signal
import sys

# Initialize AWS clients
sqs = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
sns = boto3.client('sns')
secretsmanager = boto3.client('secretsmanager')

# Environment variables
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')
S3_BUCKET = os.environ.get('S3_BUCKET')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

# Global variables
current_job = None
shutdown_requested = False

# Veraset API configuration
API_ENDPOINT = "https://platform.prd.veraset.tech"

JOBS_FILE = 'jobs.json'

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_requested
    print(f"Received signal {signum}. Gracefully shutting down...")
    shutdown_requested = True

def get_veraset_api_key() -> str:
    # Get Veraset API key from environment
    return os.environ.get('veraset_api_key')

def receive_messages_from_queue():
    """Receive messages from SQS queue"""
    try:
        response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,  # Long polling
            MessageAttributeNames=['All']
        )
        return response.get('Messages', [])
    except Exception as e:
        print(f"Error receiving messages: {e}")
        return []

def delete_message_from_queue(receipt_handle: str):
    """Delete processed message from queue"""
    try:
        sqs.delete_message(
            QueueUrl=SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle
        )
    except Exception as e:
        print(f"Error deleting message: {e}")

def update_job_status(job_id: str, status: str, error_message: str = None):
    """Update job status in DynamoDB"""
    try:
        table = dynamodb.Table('mobility-job-tracking')
        
        update_expression = "SET #status = :status, updated_at = :updated_at"
        expression_values = {
            ':status': status,
            ':updated_at': datetime.utcnow().isoformat()
        }
        
        if error_message:
            update_expression += ", error_message = :error_message"
            expression_values[':error_message'] = error_message
        
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        print(f"Error updating job status: {e}")

def send_notification(subject: str, message: str):
    """Send SNS notification"""
    try:
        # Get notification topic ARN from environment or construct it
        account_id = boto3.client('sts').get_caller_identity()['Account']
        topic_arn = f"arn:aws:sns:{AWS_REGION}:{account_id}:mobility-data-notifications"
        
        sns.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message
        )
    except Exception as e:
        print(f"Error sending notification: {e}")

def make_api_request(endpoint: str, method: str = "POST", data: Dict = None, api_key: str = None) -> Optional[Dict]:
    """Make request to Veraset API"""
    url = f"{API_ENDPOINT}/v1/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }
    
    try:
        response = requests.request(method, url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        
        try:
            return response.json()
        except json.JSONDecodeError:
            print(f"Non-JSON response from API: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        raise

def get_job_status(job_id: str, api_key: str) -> Optional[Dict]:
    """Get job status from Veraset API"""
    return make_api_request(f"job/{job_id}", method="GET", api_key=api_key)

def wait_for_job_completion(job_id: str, api_key: str, max_wait_minutes: int = 120) -> Optional[str]:
    """Wait for Veraset job to complete and return S3 location"""
    max_attempts = max_wait_minutes * 2  # Check every 30 seconds
    
    for attempt in range(max_attempts):
        if shutdown_requested:
            print("Shutdown requested, stopping job wait")
            return None
            
        try:
            status_response = get_job_status(job_id, api_key)
            if not status_response:
                print(f"No valid response from job status API (attempt {attempt + 1})")
                time.sleep(30)
                continue
                
            job_status = status_response["data"]["status"]
            
            if job_status == "SUCCESS":
                return status_response["data"]["s3_location"]["folder_path"]
            elif job_status == "FAILED":
                error_msg = status_response.get('error_message', 'Unknown error')
                raise Exception(f"Veraset job failed: {error_msg}")
            elif job_status == "CANCELLED":
                raise Exception("Veraset job was cancelled")
            
            print(f"Job status: {job_status} (attempt {attempt + 1}/{max_attempts})")
            time.sleep(30)
            
        except Exception as e:
            print(f"Error checking job status: {e}")
            time.sleep(30)
    
    raise Exception(f"Job timed out after {max_wait_minutes} minutes")

def sync_data_to_bucket(source_path: str, city_folder: str) -> bool:
    """Sync data from Veraset S3 bucket to our bucket"""
    source_bucket = "veraset-prd-platform-us-west-2"
    role_arn = "arn:aws:iam::651706782157:role/VerasetS3AccessRole"
    
    try:
        print("Assuming Veraset S3 access role...")
        
        # Assume role to access Veraset S3 bucket
        sts_client = boto3.client('sts')
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='veraset-sync-session'
        )
        
        credentials = response['Credentials']
        
        # Set up environment for AWS CLI with assumed role credentials
        env = os.environ.copy()
        env["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
        env["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
        env["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
        
        # Construct S3 sync command
        sync_command = [
            "aws", "s3", "sync",
            "--copy-props", "none",
            "--no-progress",
            "--no-follow-symlinks",
            "--exclude", "*",
            "--include", "*.parquet",
            f"s3://{source_bucket}/{source_path.lstrip('/')}",
            f"s3://{S3_BUCKET}/{city_folder}/"
        ]
        
        print(f"Syncing data from s3://{source_bucket}/{source_path} to s3://{S3_BUCKET}/{city_folder}/")
        
        # Execute sync command
        result = subprocess.run(sync_command, env=env, capture_output=True, text=True, timeout=3600)
        
        if result.returncode == 0:
            print(f"Successfully synced data to {S3_BUCKET}/{city_folder}")
            return True
        else:
            print(f"Sync failed with return code {result.returncode}")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("Sync operation timed out after 1 hour")
        return False
    except Exception as e:
        print(f"Error syncing data: {e}")
        return False

def process_mobility_job(job_data: Dict[str, Any]) -> bool:
    """Process a single mobility data job"""
    global current_job
    current_job = job_data
    
    job_id = job_data['job_id']
    city_id = job_data['city_id']
    city_name = job_data['city_name']
    country = job_data['country']
    state_province = job_data.get('state_province', '')
    process_date = job_data['process_date']
    
    print(f"Processing job {job_id} for {city_name}, {country} on {process_date}")
    
    try:
        # Update job status to processing
        update_job_status(job_id, 'processing')
        
        # Get API key
        api_key = get_veraset_api_key()
        
        # Create Veraset API payload
        payload = {
            "date_range": {
                "from_date": process_date,
                "to_date": process_date
            },
            "schema_type": "FULL",
            "geo_radius": [{
                "poi_id": f"{city_id}_center",
                "latitude": job_data['latitude'],
                "longitude": job_data['longitude'],
                "distance_in_meters": job_data.get('radius_meters', 50000)
            }]
        }
        
        print("Submitting job to Veraset API...")
        response = make_api_request("movement/job/pings", data=payload, api_key=api_key)
        
        if not response:
            raise Exception("No response from Veraset API")
        
        veraset_job_id = response.get("data", {}).get("job_id")
        if not veraset_job_id:
            raise Exception("No job_id received from Veraset API")
        
        print(f"Veraset job submitted: {veraset_job_id}")
        
        # Wait for job completion
        print("Waiting for Veraset job completion...")
        s3_location = wait_for_job_completion(veraset_job_id, api_key)
        
        if not s3_location:
            raise Exception("Job completion wait was interrupted")
        
        print(f"Veraset job completed. Data location: {s3_location}")
        
        # Create destination folder path
        if state_province:
            city_folder = f"data/{country}/{state_province}/{city_name}"
        else:
            city_folder = f"data/{country}/{city_name}"
        
        # Sync data to our bucket
        print("Syncing data to our S3 bucket...")
        sync_success = sync_data_to_bucket(s3_location, city_folder)
        
        if not sync_success:
            raise Exception("Data sync failed")
        
        # Update job status to completed
        update_job_status(job_id, 'completed')
        
        print(f"Job {job_id} completed successfully!")
        return True
        
    except Exception as e:
        error_msg = f"Job {job_id} failed: {str(e)}"
        print(error_msg)
        
        # Update job status to failed
        update_job_status(job_id, 'failed', str(e))
        
        # Send failure notification
        send_notification(
            subject=f"Mobility Data Job Failed - {city_name}",
            message=f"Job ID: {job_id}\nCity: {city_name}, {country}\nDate: {process_date}\nError: {str(e)}"
        )
        
        return False
    
    finally:
        current_job = None

def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return []
    with open(JOBS_FILE, 'r') as f:
        return json.load(f)

def save_jobs(jobs):
    with open(JOBS_FILE, 'w') as f:
        json.dump(jobs, f, indent=2)

def main():
    print("Starting mobility data worker (local mode)...")
    jobs = load_jobs()
    for job in jobs:
        if job.get('status') in ('completed', 'failed'):
            continue
        print(f"Processing job: {job['job_id']} for {job['city_name']} on {job['process_date']}")
        success = process_mobility_job(job)
        job['status'] = 'completed' if success else 'failed'
        save_jobs(jobs)
    print("All jobs processed. Worker shutting down...")

if __name__ == "__main__":
    main()