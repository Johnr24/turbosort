#!/usr/bin/env python3
"""
TurboSort - Simple Directory Watcher and File Sorter

Monitors a source directory and sorts files to destination directories
based on .turbosort files.
"""

import os
import time
import json
import shutil
import logging
import argparse
import re
import xxhash
import io
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# S3 imports
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Directories to use - read from environment variables with defaults
SOURCE_DIR = os.environ.get('SOURCE_DIR', 'source')
DEST_DIR = os.environ.get('DEST_DIR', 'destination')
TURBOSORT_FILE = '.turbosort'
HISTORY_DIR = os.environ.get('HISTORY_DIR', os.path.join(os.environ.get('HISTORY_VOLUME', 'history')))
HISTORY_FILE = os.environ.get('HISTORY_FILE', os.path.join(HISTORY_DIR, 'turbosort_history.json'))
# Enable year prefix feature
ENABLE_YEAR_PREFIX = os.environ.get('ENABLE_YEAR_PREFIX', 'false').lower() in ('true', 'yes', '1')
# Option to force re-copy of files regardless of history
FORCE_RECOPY = os.environ.get('FORCE_RECOPY', 'false').lower() in ('true', 'yes', '1')
# How often to perform a full rescan (in seconds), 0 to disable
RESCAN_INTERVAL = int(os.environ.get('RESCAN_INTERVAL', '60'))
# Enable/disable drive suffix feature
ENABLE_DRIVE_SUFFIX = os.environ.get('ENABLE_DRIVE_SUFFIX', 'true').lower() in ('true', 'yes', '1')
# Configurable drive suffix
DRIVE_SUFFIX = os.environ.get('DRIVE_SUFFIX', 'incoming')

# S3 configuration
USE_S3_SOURCE = os.environ.get('USE_S3_SOURCE', 'false').lower() in ('true', 'yes', '1')
S3_ENDPOINT = os.environ.get('S3_ENDPOINT', 'http://minio:9000')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY', 'minioadmin')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY', 'minioadmin')
S3_BUCKET = os.environ.get('S3_BUCKET', 'turbosort-source')
S3_PATH_PREFIX = os.environ.get('S3_PATH_PREFIX', '')
S3_REGION = os.environ.get('S3_REGION', 'us-east-1')
S3_POLL_INTERVAL = int(os.environ.get('S3_POLL_INTERVAL', '30'))


class S3Handler:
    """Handles S3 operations for reading and listing files."""
    
    def __init__(self):
        """Initialize S3 client and resources."""
        # Configure S3 client with custom endpoint for MinIO compatibility
        self.s3_client = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(signature_version='s3v4')
        )
        
        # S3 resource for higher-level operations
        self.s3_resource = boto3.resource(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(signature_version='s3v4')
        )
        
        # Reference to the bucket
        self.bucket = self.s3_resource.Bucket(S3_BUCKET)
        
        # Store last known object list for detecting changes
        self.last_known_objects = {}
        
        logger.info(f"S3 handler initialized: endpoint={S3_ENDPOINT}, bucket={S3_BUCKET}")
    
    def list_objects(self, prefix=''):
        """
        List objects in the S3 bucket with the given prefix.
        
        Args:
            prefix (str): Object prefix to filter by
            
        Returns:
            dict: Dict of objects with key as full path and value as object metadata
        """
        objects = {}
        
        # Combine the global path prefix with the provided prefix
        full_prefix = S3_PATH_PREFIX
        if prefix:
            full_prefix = os.path.join(full_prefix, prefix) if full_prefix else prefix
        
        # Remove leading slash if present (S3 doesn't use leading slashes in keys)
        if full_prefix.startswith('/'):
            full_prefix = full_prefix[1:]
        
        try:
            # Use pagination to handle large buckets
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=full_prefix)
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Store the object with its metadata
                        objects[obj['Key']] = {
                            'size': obj['Size'],
                            'last_modified': obj['LastModified'].isoformat(),
                            'etag': obj['ETag']
                        }
            
            return objects
        except ClientError as e:
            logger.error(f"Error listing S3 objects: {e}")
            return {}
    
    def read_object(self, key):
        """
        Read an object from the S3 bucket.
        
        Args:
            key (str): Object key
            
        Returns:
            bytes: Object content or None if error
        """
        try:
            response = self.s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            return response['Body'].read()
        except ClientError as e:
            logger.error(f"Error reading S3 object {key}: {e}")
            return None
    
    def get_object_metadata(self, key):
        """
        Get object metadata without downloading the content.
        
        Args:
            key (str): Object key
            
        Returns:
            dict: Object metadata or None if error
        """
        try:
            response = self.s3_client.head_object(Bucket=S3_BUCKET, Key=key)
            return {
                'size': response['ContentLength'],
                'last_modified': response['LastModified'].isoformat(),
                'etag': response['ETag']
            }
        except ClientError as e:
            logger.error(f"Error getting S3 object metadata for {key}: {e}")
            return None
    
    def find_changes(self):
        """
        Check for changes in the S3 bucket since the last check.
        
        Returns:
            dict: Dict with 'new', 'modified', and 'deleted' lists of object keys
        """
        current_objects = self.list_objects()
        changes = {
            'new': [],
            'modified': [],
            'deleted': []
        }
        
        # Look for new or modified objects
        for key, metadata in current_objects.items():
            if key not in self.last_known_objects:
                changes['new'].append(key)
            elif metadata['etag'] != self.last_known_objects[key]['etag']:
                changes['modified'].append(key)
        
        # Look for deleted objects
        for key in self.last_known_objects:
            if key not in current_objects:
                changes['deleted'].append(key)
        
        # Update the last known objects
        self.last_known_objects = current_objects
        
        return changes
    
    def list_dirs(self, prefix=''):
        """
        List directories (common prefixes) in S3.
        
        Args:
            prefix (str): Directory prefix
            
        Returns:
            list: List of directory paths
        """
        try:
            # Remove leading slash if present
            if prefix.startswith('/'):
                prefix = prefix[1:]
            
            # Combine with global path prefix if needed
            if S3_PATH_PREFIX:
                prefix = os.path.join(S3_PATH_PREFIX, prefix) if prefix else S3_PATH_PREFIX
            
            # Add trailing slash to simulate directories
            if prefix and not prefix.endswith('/'):
                prefix += '/'
            
            # Use delimiter to list directories
            response = self.s3_client.list_objects_v2(
                Bucket=S3_BUCKET,
                Prefix=prefix,
                Delimiter='/'
            )
            
            dirs = []
            if 'CommonPrefixes' in response:
                for common_prefix in response['CommonPrefixes']:
                    dir_path = common_prefix['Prefix']
                    dirs.append(dir_path)
            
            return dirs
        except ClientError as e:
            logger.error(f"Error listing S3 directories: {e}")
            return []
    
    def get_object_path(self, key):
        """
        Convert an S3 key to a consistent path format.
        
        Args:
            key (str): S3 object key
            
        Returns:
            str: Normalized path for the object
        """
        # For consistency with file paths, ensure the path starts with /
        return f"/{key}" if not key.startswith('/') else key


class TurboSorter:
    """Handles sorting files based on .turbosort files."""
    
    def __init__(self):
        """Initialize the TurboSorter with default directories."""
        # Normalize paths to ensure no trailing slash issues
        self.source_dir = Path(os.path.normpath(SOURCE_DIR))
        self.dest_dir = Path(os.path.normpath(DEST_DIR))
        
        # Store the source/dest directory for container-to-host path mapping
        self.source_container_path = '/app/source/'
        self.dest_container_path = '/app/destination/'
        self.running_in_container = os.path.exists('/.dockerenv')
        
        # Initialize S3 handler if using S3 source
        self.use_s3_source = USE_S3_SOURCE
        self.s3_handler = None
        if self.use_s3_source:
            self.s3_handler = S3Handler()
            logger.info(f"Using S3 as source: {S3_ENDPOINT}/{S3_BUCKET}/{S3_PATH_PREFIX}")
        
        if self.running_in_container:
            logger.info("Running in Docker container - will translate paths accordingly")
        
        # Ensure directories exist
        if not self.use_s3_source:
            self.source_dir.mkdir(parents=True, exist_ok=True)
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure history directory exists
        Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)
        
        # Track copied files - key: source path, value: (destination path, timestamp)
        self.copied_files = {}
        
        # Load previous history if available
        self.load_history()
        
        logger.info(f"TurboSort initialized: watching {S3_BUCKET if self.use_s3_source else self.source_dir}")
        logger.info(f"Files will be sorted to {self.dest_dir}")
        logger.info(f"History file: {HISTORY_FILE}")
        
        if ENABLE_YEAR_PREFIX:
            logger.info("Year prefix feature is enabled")
        
        if ENABLE_DRIVE_SUFFIX:
            logger.info(f"Drive suffix feature is enabled with suffix: '{DRIVE_SUFFIX}'")
        else:
            logger.info("Drive suffix feature is disabled")
        
        if FORCE_RECOPY:
            logger.warning("Force re-copy mode is enabled - all files will be copied regardless of history")
    
    def extract_year(self, path_string):
        """
        Extract a 4-digit year from a path string.
        
        Args:
            path_string (str): The path string to search for a year
            
        Returns:
            str or None: The extracted year or None if not found
        """
        if not path_string:
            return None
        
        # Look for a 4-digit number that could be a year (between 1900 and 2099)
        year_match = re.search(r'(19\d{2}|20\d{2})', path_string)
        if year_match:
            return year_match.group(1)
        return None
    
    def get_file_identifier(self, file_path):
        """
        Generate a unique identifier for a file based on its path and attributes.
        
        The identifier is based on BOTH the file contents/attributes AND its source folder location.
        This ensures that identical files in different folders are treated as different files.
        
        Args:
            file_path (Path): Path to the file
            
        Returns:
            str: A unique identifier for the file
        """
        if not file_path.exists():
            return None
        
        # Get file stats
        stats = file_path.stat()
        
        # Use the full source path as part of the identifier
        # This ensures that identical files in different folders are treated as different
        source_path = str(file_path)
        
        # Create a unique identifier based on path, size and modification time
        # The source path includes the folder location, making it a path+file combination
        identifier = f"{source_path}:{stats.st_size}:{stats.st_mtime}"
        
        # Use xxhash for extremely fast hashing - much better than cryptographic hashes for this purpose
        return xxhash.xxh64(identifier.encode()).hexdigest()
    
    def process_directory(self, directory):
        """
        Process a directory with a .turbosort file.
        
        Args:
            directory (Path or str): Directory to process
        """
        if self.use_s3_source:
            # S3 path handling
            s3_dir_path = str(directory)
            # Remove leading slash if present (S3 doesn't use leading slashes in keys)
            if s3_dir_path.startswith('/'):
                s3_dir_path = s3_dir_path[1:]
            
            # Ensure the path ends with a slash for S3 directory semantics
            if not s3_dir_path.endswith('/'):
                s3_dir_path += '/'
            
            # Check for .turbosort file in this directory
            turbosort_key = os.path.join(s3_dir_path, TURBOSORT_FILE)
            
            # Read the .turbosort file content from S3
            turbosort_content = self.s3_handler.read_object(turbosort_key)
            if turbosort_content is None:
                return  # No .turbosort file or error reading it
            
            try:
                # Decode the content and extract the destination directory
                dest_subdir = turbosort_content.decode('utf-8').strip()
                
                if not dest_subdir:
                    logger.warning(f"Empty destination in S3 {turbosort_key}")
                    return
                
                # Normalize the destination path
                dest_subdir = os.path.normpath(dest_subdir)
                logger.info(f"Processing S3 directory with .turbosort path: {dest_subdir}")
                
                # Create the destination directory with the appropriate path structure
                if ENABLE_YEAR_PREFIX:
                    # Try to extract year from the destination path
                    year = self.extract_year(dest_subdir)
                    if year and year.isdigit() and len(year) == 4:
                        # Use the year as a prefix
                        try:
                            if ENABLE_DRIVE_SUFFIX:
                                target_dir = self.dest_dir / year / dest_subdir / DRIVE_SUFFIX
                            else:
                                target_dir = self.dest_dir / year / dest_subdir
                            logger.info(f"Using year prefix: {year} for path: {dest_subdir}")
                        except Exception as e:
                            logger.error(f"Error creating path with year prefix: {e}")
                            # Fallback to standard path without year prefix
                            if ENABLE_DRIVE_SUFFIX:
                                target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                            else:
                                target_dir = self.dest_dir / dest_subdir
                    else:
                        # If no year found, use the standard path
                        if ENABLE_DRIVE_SUFFIX:
                            target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                        else:
                            target_dir = self.dest_dir / dest_subdir
                        logger.warning(f"No valid year found in path: {dest_subdir}, using standard path")
                else:
                    # Standard path without year prefix
                    if ENABLE_DRIVE_SUFFIX:
                        target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                    else:
                        target_dir = self.dest_dir / dest_subdir
                
                # Ensure the target_dir is a valid path
                try:
                    target_dir = Path(os.path.normpath(str(target_dir)))
                    logger.info(f"Final target directory: {target_dir}")
                    target_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error(f"Invalid target directory path: {e}")
                    return
                
                # List objects in the S3 directory
                s3_objects = self.s3_handler.list_objects(s3_dir_path)
                
                # Process each file in the directory
                for object_key, metadata in s3_objects.items():
                    # Skip the .turbosort file and any directory markers
                    if object_key.endswith(TURBOSORT_FILE) or object_key.endswith('/'):
                        continue
                    
                    # Get just the filename from the S3 key
                    file_name = os.path.basename(object_key)
                    
                    # Create unique file identifier for S3 object
                    file_identifier = object_key + ':' + metadata['etag']
                    file_identifier = xxhash.xxh64(file_identifier.encode()).hexdigest()
                    
                    # Check if this object has already been processed
                    if not FORCE_RECOPY and object_key in self.copied_files:
                        # Check if the file identifier matches what we have in history
                        stored_identifier = self.copied_files[object_key].get('identifier')
                        if stored_identifier and stored_identifier == file_identifier:
                            logger.info(f"Skipping already processed S3 object: {file_name} (one-and-done)")
                            continue
                        else:
                            # Only process if the source file has changed
                            logger.info(f"S3 object {file_name} has changed, processing again")
                    
                    # Copy the file from S3 to local destination
                    target_file = target_dir / file_name
                    
                    try:
                        # Ensure target directory exists
                        target_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Download S3 object and save to local file
                        object_content = self.s3_handler.read_object(object_key)
                        if object_content is not None:
                            with open(target_file, 'wb') as f:
                                f.write(object_content)
                            
                            logger.info(f"Copied from S3: {file_name} to {target_dir}/")
                            
                            # Record the copied file
                            timestamp = datetime.now()
                            self.copied_files[object_key] = {
                                'destination': str(target_file),
                                'timestamp': timestamp.isoformat(),
                                'size': metadata['size'],
                                'identifier': file_identifier
                            }
                            
                            # Save history after each copy
                            self.save_history()
                    except Exception as e:
                        logger.error(f"Error copying S3 object {file_name}: {str(e)}")
                
            except Exception as e:
                logger.error(f"Error processing S3 directory {s3_dir_path}: {str(e)}")

        else:
            # Local filesystem handling - original code
            # Check if the turbosort file exists in this directory
            turbosort_path = directory / TURBOSORT_FILE
            
            if not turbosort_path.exists():
                return
            
            try:
                # Read the destination directory from the .turbosort file
                with open(turbosort_path, 'r') as f:
                    dest_subdir = f.read().strip()
                
                if not dest_subdir:
                    logger.warning(f"Empty destination in {turbosort_path}")
                    return
                
                # Normalize the destination path
                dest_subdir = os.path.normpath(dest_subdir)
                logger.info(f"Processing directory with .turbosort path: {dest_subdir}")
                
                # Create the destination directory with the appropriate path structure
                if ENABLE_YEAR_PREFIX:
                    # Try to extract year from the destination path
                    year = self.extract_year(dest_subdir)
                    if year and year.isdigit() and len(year) == 4:
                        # Don't duplicate the destination path - just use the year as a prefix
                        # and keep the original destination path
                        try:
                            if ENABLE_DRIVE_SUFFIX:
                                target_dir = self.dest_dir / year / dest_subdir / DRIVE_SUFFIX
                            else:
                                target_dir = self.dest_dir / year / dest_subdir
                            logger.info(f"Using year prefix: {year} for path: {dest_subdir}")
                        except Exception as e:
                            logger.error(f"Error creating path with year prefix: {e}")
                            # Fallback to standard path without year prefix
                            if ENABLE_DRIVE_SUFFIX:
                                target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                            else:
                                target_dir = self.dest_dir / dest_subdir
                    else:
                        # If no year found, use the standard path
                        if ENABLE_DRIVE_SUFFIX:
                            target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                        else:
                            target_dir = self.dest_dir / dest_subdir
                        logger.warning(f"No valid year found in path: {dest_subdir}, using standard path")
                else:
                    # Standard path without year prefix
                    if ENABLE_DRIVE_SUFFIX:
                        target_dir = self.dest_dir / dest_subdir / DRIVE_SUFFIX
                    else:
                        target_dir = self.dest_dir / dest_subdir
                
                # Ensure the target_dir is a valid path
                try:
                    target_dir = Path(os.path.normpath(str(target_dir)))
                    logger.info(f"Final target directory: {target_dir}")
                    target_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error(f"Invalid target directory path: {e}")
                    return
                
                # Copy all files except the .turbosort file
                for file_path in directory.iterdir():
                    if file_path.is_file() and file_path.name != TURBOSORT_FILE:
                        # Skip files that don't exist (could have been deleted after directory listing)
                        if not file_path.exists():
                            logger.warning(f"File disappeared during processing: {file_path}")
                            continue
                            
                        # Get a unique identifier for the file
                        file_identifier = self.get_file_identifier(file_path)
                        file_path_str = str(file_path)
                        
                        # Check if this EXACT file+folder combination has already been processed (ONE-AND-DONE BEHAVIOR)
                        # We identify files by both their contents/attributes AND their source location
                        # This means identical files in different source folders are treated as different files
                        if not FORCE_RECOPY and file_path_str in self.copied_files:
                            # Check if the file identifier matches what we have in history
                            stored_identifier = self.copied_files[file_path_str].get('identifier')
                            if stored_identifier and stored_identifier == file_identifier:
                                logger.info(f"Skipping already processed file: {file_path.name} (one-and-done)")
                                continue
                            else:
                                # Only process if the source file has changed
                                logger.info(f"Source file {file_path.name} has changed, processing again")
                        
                        # Copy the file if it's not in history or the source has changed
                        target_file = target_dir / file_path.name
                        
                        try:
                            # Ensure target directory exists, in case it was deleted
                            target_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Copy the file
                            shutil.copy2(file_path, target_file)
                            logger.info(f"Copied: {file_path.name} to {target_dir}/")
                            
                            # Record the copied file with timestamp and identifier
                            timestamp = datetime.now()
                            self.copied_files[file_path_str] = {
                                'destination': str(target_file),
                                'timestamp': timestamp.isoformat(),
                                'size': file_path.stat().st_size,
                                'identifier': file_identifier
                            }
                            
                            # Save history after each copy
                            self.save_history()
                        except Exception as e:
                            logger.error(f"Error copying {file_path.name}: {str(e)}")
            
            except Exception as e:
                logger.error(f"Error processing {directory}: {str(e)}")
    
    def scan_all(self):
        """Scan all directories for .turbosort files."""
        logger.info(f"Scanning for .turbosort files...")
        
        # First, clean history by removing entries for files that no longer exist
        self.clean_history()
        
        if self.use_s3_source:
            # For S3, we need a different approach to scan directories
            self._scan_s3_directories("")
        else:
            # Walk through all subdirectories in local filesystem
            for root, _, _ in os.walk(self.source_dir):
                self.process_directory(Path(root))
    
    def _scan_s3_directories(self, prefix=""):
        """
        Recursively scan S3 directories for .turbosort files.
        
        Args:
            prefix (str): Directory prefix to scan
        """
        logger.info(f"Scanning S3 directory: {prefix or 'root'}")
        
        # Check if the current directory has a .turbosort file
        self.process_directory(prefix)
        
        # List subdirectories (common prefixes)
        dirs = self.s3_handler.list_dirs(prefix)
        
        # Recursively scan each subdirectory
        for dir_prefix in dirs:
            self._scan_s3_directories(dir_prefix)
    
    def clean_history(self):
        """Remove entries from history for files that no longer exist."""
        files_to_remove = []
        
        # Check each file in history
        for file_path_str in self.copied_files:
            if self.use_s3_source:
                # For S3 sources, check if the object still exists in the bucket
                if file_path_str.startswith('/'):
                    # Remove leading slash for S3 keys
                    s3_key = file_path_str[1:]
                else:
                    s3_key = file_path_str
                
                # Check if this is a valid S3 key format
                if not s3_key.startswith('/app/'):  # Not a container path
                    # Try to get metadata for the object
                    metadata = self.s3_handler.get_object_metadata(s3_key)
                    if metadata is None:
                        files_to_remove.append(file_path_str)
                        logger.info(f"Removing from history: {file_path_str} (S3 object no longer exists)")
            else:
                # Local filesystem handling - original code
                # First try the path as is
                file_path = Path(file_path_str)
                
                # Check if this is a container path and adjust accordingly
                if self.running_in_container:
                    # We're in the container and paths should be container paths
                    if not file_path_str.startswith(self.source_container_path):
                        # Skip files not in the source directory
                        continue
                else:
                    # We're running on the host, but file paths in history might be container paths
                    if file_path_str.startswith('/app/'):
                        # Convert container path to host path
                        if file_path_str.startswith(self.source_container_path):
                            relative_path = file_path_str[len(self.source_container_path):]
                            host_path = self.source_dir / relative_path
                            file_path = host_path
                
                # If file doesn't exist anymore, mark for removal
                try:
                    if not file_path.exists():
                        files_to_remove.append(file_path_str)
                        logger.info(f"Removing from history: {file_path_str} (file no longer exists)")
                except Exception as e:
                    logger.warning(f"Error checking if file exists: {file_path_str} - {e}")
        
        # Remove marked files from history
        for file_path_str in files_to_remove:
            del self.copied_files[file_path_str]
        
        # Save updated history
        if files_to_remove:
            logger.info(f"Removed {len(files_to_remove)} non-existent files from history")
            self.save_history()
    
    def get_copied_files(self):
        """
        Return information about all files that have been copied.
        
        Returns:
            dict: Information about copied files
        """
        return self.copied_files
    
    def get_copy_stats(self):
        """
        Return statistics about copied files.
        
        Returns:
            dict: Statistics about copied files
        """
        total_size = sum(info['size'] for info in self.copied_files.values())
        return {
            'total_files': len(self.copied_files),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2) if total_size > 0 else 0
        }
    
    def save_history(self):
        """Save the copy history to a file."""
        try:
            with open(HISTORY_FILE, 'w') as f:
                json.dump(self.copied_files, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {str(e)}")
    
    def load_history(self):
        """Load copy history from file if it exists."""
        history_path = Path(HISTORY_FILE)
        if history_path.exists():
            try:
                with open(history_path, 'r') as f:
                    self.copied_files = json.load(f)
                logger.info(f"Loaded history for {len(self.copied_files)} files")
            except Exception as e:
                logger.error(f"Error loading history: {str(e)}")
                # If there's an error loading, start with an empty history
                self.copied_files = {}
        else:
            logger.info(f"No history file found at {history_path}, starting with empty history")
            self.copied_files = {}


class FileChangeHandler(FileSystemEventHandler):
    """Handles file system events."""
    
    def __init__(self, sorter):
        self.sorter = sorter
        # Track which directories we need to process
        self.dirs_to_process = set()
        # Throttle time to batch events (in seconds)
        self.throttle_time = 0.5
        # Last time we processed any events
        self.last_process_time = time.time()
        super().__init__()
    
    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            path = Path(event.src_path)
            
            # If a .turbosort file is created, process its directory immediately
            if path.name == TURBOSORT_FILE:
                logger.info(f"New .turbosort file detected: {path}")
                self.sorter.process_directory(path.parent)
            else:
                # For other files, add the parent directory to the processing queue
                # Find the closest parent directory with a .turbosort file
                parent_dir = path.parent
                while parent_dir != Path(SOURCE_DIR) and parent_dir != Path('/'):
                    if (parent_dir / TURBOSORT_FILE).exists():
                        self.dirs_to_process.add(parent_dir)
                        logger.info(f"Queued directory for processing due to new file: {parent_dir}")
                        break
                    parent_dir = parent_dir.parent
    
    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            path = Path(event.src_path)
            
            # If a .turbosort file is modified, process its directory immediately
            if path.name == TURBOSORT_FILE:
                logger.info(f"Modified .turbosort file detected: {path}")
                self.sorter.process_directory(path.parent)
    
    def on_deleted(self, event):
        """Handle file deletion events (for .turbosort files)."""
        if not event.is_directory:
            path = Path(event.src_path)
            
            # If a .turbosort file is deleted, log it
            if path.name == TURBOSORT_FILE:
                logger.info(f".turbosort file deleted: {path}")
    
    def process_queued_dirs(self):
        """Process any directories that have queued changes."""
        current_time = time.time()
        
        # Only process if enough time has passed since the last event (throttling)
        if current_time - self.last_process_time >= self.throttle_time and self.dirs_to_process:
            logger.info(f"Processing {len(self.dirs_to_process)} directories with changes")
            
            for dir_path in self.dirs_to_process:
                try:
                    self.sorter.process_directory(dir_path)
                except Exception as e:
                    logger.error(f"Error processing queued directory {dir_path}: {e}")
            
            # Clear the queue
            self.dirs_to_process.clear()
            self.last_process_time = current_time


def print_stats(sorter):
    """Print statistics about copied files."""
    stats = sorter.get_copy_stats()
    
    logger.info("=== TurboSort Copy Statistics ===")
    logger.info(f"Total files copied: {stats['total_files']}")
    logger.info(f"Total size: {stats['total_size_mb']} MB")
    logger.info("===============================")


def display_history(sorter, detailed=False):
    """
    Display file copy history.
    
    Args:
        sorter (TurboSorter): The sorter instance
        detailed (bool): Whether to show detailed information
    """
    copied_files = sorter.get_copied_files()
    
    if not copied_files:
        print("No files have been copied yet.")
        return
    
    print(f"\n{'='*70}")
    print(f"TurboSort Copy History - {len(copied_files)} files")
    print(f"{'='*70}")
    
    if detailed:
        for source, info in copied_files.items():
            print(f"\nSource: {source}")
            print(f"Destination: {info['destination']}")
            print(f"Timestamp: {info['timestamp']}")
            print(f"Size: {info['size']} bytes ({round(info['size'] / 1024, 2)} KB)")
            print("-" * 70)
    else:
        # Simple tabular format
        print(f"{'Source':<40} | {'Destination':<40} | {'Size':<10}")
        print(f"{'-'*40}-+-{'-'*40}-+-{'-'*10}")
        
        for source, info in copied_files.items():
            size_kb = round(info['size'] / 1024, 2)
            print(f"{Path(source).name:<40} | {Path(info['destination']).name:<40} | {size_kb:<10} KB")
    
    # Print summary
    stats = sorter.get_copy_stats()
    print(f"\nTotal: {stats['total_files']} files, {stats['total_size_mb']} MB")
    print(f"{'='*70}\n")


def main():
    """Main function to run TurboSort."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='TurboSort - Directory watcher and file sorter')
    parser.add_argument('--history', action='store_true', help='Display copy history')
    parser.add_argument('--detailed', action='store_true', help='Show detailed history')
    parser.add_argument('--clear-history', action='store_true', help='Clear history file and start fresh')
    parser.add_argument('--scan-now', action='store_true', help='Perform a full scan immediately, then exit')
    args = parser.parse_args()
    
    # Initialize the sorter
    sorter = TurboSorter()
    
    # Handle clear-history request
    if args.clear_history:
        try:
            sorter.copied_files = {}
            sorter.save_history()
            print(f"History file cleared: {HISTORY_FILE}")
            return
        except Exception as e:
            print(f"Error clearing history: {e}")
            return
    
    # If --history is specified, just display history and exit
    if args.history:
        display_history(sorter, args.detailed)
        return
    
    # If --scan-now is specified, just do a scan and exit
    if args.scan_now:
        print("Performing a full scan of all directories...")
        sorter.scan_all()
        print_stats(sorter)
        return
    
    # Otherwise, proceed with normal operation
    # Do an initial scan
    sorter.scan_all()
    
    # Print initial stats
    if sorter.get_copy_stats()['total_files'] > 0:
        print_stats(sorter)
    
    # Use different approaches for S3 vs local directory watching
    if sorter.use_s3_source:
        # For S3, use polling mechanism
        try:
            logger.info(f"TurboSort running with S3 source. Polling interval: {S3_POLL_INTERVAL} seconds")
            if RESCAN_INTERVAL > 0:
                logger.info(f"Full bucket rescan will occur every {RESCAN_INTERVAL} seconds")
            
            # Periodically print statistics, check for changes, and run a full scan if enabled
            last_stats_time = time.time()
            last_scan_time = time.time()
            last_poll_time = time.time()
            
            while True:
                # Sleep briefly to avoid high CPU usage
                time.sleep(0.1)
                
                current_time = time.time()
                
                # Poll for S3 changes
                if current_time - last_poll_time >= S3_POLL_INTERVAL:
                    logger.info(f"Polling S3 for changes...")
                    
                    try:
                        # Find changed, new, or deleted objects
                        changes = sorter.s3_handler.find_changes()
                        
                        # Process any directories with new or modified files
                        dirs_to_process = set()
                        
                        # Collect directories containing new or modified files
                        for changed_type in ['new', 'modified']:
                            for object_key in changes[changed_type]:
                                # Get the directory path from the object key
                                dir_path = os.path.dirname(object_key)
                                if dir_path:
                                    dirs_to_process.add(dir_path)
                        
                        # Process each directory with changes
                        for dir_path in dirs_to_process:
                            logger.info(f"Processing S3 directory with changes: {dir_path}")
                            sorter.process_directory(dir_path)
                        
                    except Exception as e:
                        logger.error(f"Error polling S3: {e}")
                    
                    last_poll_time = current_time
                
                # Print stats every 5 minutes if files have been copied
                if current_time - last_stats_time >= 300:  # 5 minutes in seconds
                    if sorter.get_copy_stats()['total_files'] > 0:
                        print_stats(sorter)
                    last_stats_time = current_time
                
                # Perform a full rescan if enabled
                if RESCAN_INTERVAL > 0 and current_time - last_scan_time >= RESCAN_INTERVAL:
                    logger.info(f"Performing scheduled full S3 scan (every {RESCAN_INTERVAL} seconds)")
                    sorter.scan_all()
                    last_scan_time = current_time
                    
        except KeyboardInterrupt:
            logger.info("Stopping TurboSort...")
            
            # Print final statistics before exiting
            if sorter.get_copy_stats()['total_files'] > 0:
                logger.info("Final statistics:")
                print_stats(sorter)
    else:
        # For local filesystem, use watchdog
        # Set up the file watcher
        event_handler = FileChangeHandler(sorter)
        observer = Observer()
        observer.schedule(event_handler, SOURCE_DIR, recursive=True)
        observer.start()
        
        try:
            logger.info("TurboSort running. Press Ctrl+C to stop.")
            if RESCAN_INTERVAL > 0:
                logger.info(f"Full directory rescan will occur every {RESCAN_INTERVAL} seconds")
            
            # Periodically print statistics and run a full scan if enabled
            last_stats_time = time.time()
            last_scan_time = time.time()
            
            while True:
                # Check if there are any directories with changes to process
                event_handler.process_queued_dirs()
                
                # Sleep briefly to avoid high CPU usage
                time.sleep(0.1)
                
                current_time = time.time()
                
                # Print stats every 5 minutes if files have been copied
                if current_time - last_stats_time >= 300:  # 5 minutes in seconds
                    if sorter.get_copy_stats()['total_files'] > 0:
                        print_stats(sorter)
                    last_stats_time = current_time
                
                # Perform a full rescan if enabled
                if RESCAN_INTERVAL > 0 and current_time - last_scan_time >= RESCAN_INTERVAL:
                    logger.info(f"Performing scheduled full directory scan (every {RESCAN_INTERVAL} seconds)")
                    sorter.scan_all()
                    last_scan_time = current_time
                    
        except KeyboardInterrupt:
            logger.info("Stopping TurboSort...")
            
            # Print final statistics before exiting
            if sorter.get_copy_stats()['total_files'] > 0:
                logger.info("Final statistics:")
                print_stats(sorter)
                
            observer.stop()
        
        observer.join()


if __name__ == "__main__":
    main() 