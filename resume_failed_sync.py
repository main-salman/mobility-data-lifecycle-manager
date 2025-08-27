#!/usr/bin/env python3
"""
Script to resume failed sync operations and recover from partial failures
"""

import os
import json
import logging
from datetime import datetime
from glob import glob
from utils import load_sync_progress, cleanup_sync_progress, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

def find_failed_syncs():
    """Find all failed/partial sync operations"""
    progress_files = glob("sync_progress_*.json")
    failed_syncs = []
    
    for progress_file in progress_files:
        try:
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            
            # Check if sync was completed
            if progress.get('status') != 'completed':
                failed_syncs.append(progress)
                logger.info(f"Found incomplete sync: {progress.get('sync_id')} - {progress.get('city', 'unknown city')}")
        except Exception as e:
            logger.error(f"Error reading progress file {progress_file}: {e}")
    
    return failed_syncs

def cleanup_old_progress_files(max_age_hours=24):
    """Clean up old progress files"""
    progress_files = glob("sync_progress_*.json")
    current_time = datetime.now()
    
    for progress_file in progress_files:
        try:
            file_time = datetime.fromtimestamp(os.path.getmtime(progress_file))
            age_hours = (current_time - file_time).total_seconds() / 3600
            
            if age_hours > max_age_hours:
                os.remove(progress_file)
                logger.info(f"Cleaned up old progress file: {progress_file} (age: {age_hours:.1f} hours)")
        except Exception as e:
            logger.error(f"Error processing progress file {progress_file}: {e}")

def main():
    logger.info("=== Sync Recovery Tool ===")
    
    # Find failed syncs
    failed_syncs = find_failed_syncs()
    
    if not failed_syncs:
        logger.info("No failed syncs found")
    else:
        logger.info(f"Found {len(failed_syncs)} incomplete syncs:")
        for sync in failed_syncs:
            logger.info(f"  - {sync.get('sync_id')}: {sync.get('city')} ({sync.get('completed_files', 0)}/{sync.get('total_files', 0)} files)")
    
    # Clean up old progress files
    cleanup_old_progress_files()
    
    logger.info("Recovery scan complete")

if __name__ == '__main__':
    main()