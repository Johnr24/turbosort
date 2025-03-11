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
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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
HISTORY_FILE = os.environ.get('HISTORY_FILE', 'turbosort_history.json')
# Enable year prefix feature
ENABLE_YEAR_PREFIX = os.environ.get('ENABLE_YEAR_PREFIX', 'false').lower() in ('true', 'yes', '1')


class TurboSorter:
    """Handles sorting files based on .turbosort files."""
    
    def __init__(self):
        """Initialize the TurboSorter with default directories."""
        # Normalize paths to ensure no trailing slash issues
        self.source_dir = Path(os.path.normpath(SOURCE_DIR))
        self.dest_dir = Path(os.path.normpath(DEST_DIR))
        
        # Ensure directories exist
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Track copied files - key: source path, value: (destination path, timestamp)
        self.copied_files = {}
        
        # Load previous history if available
        self.load_history()
        
        logger.info(f"TurboSort initialized: watching {self.source_dir}")
        logger.info(f"Files will be sorted to {self.dest_dir}")
        if ENABLE_YEAR_PREFIX:
            logger.info("Year prefix feature is enabled")
    
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
    
    def process_directory(self, directory):
        """
        Process a directory with a .turbosort file.
        
        Args:
            directory (Path): Directory to process
        """
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
                        target_dir = self.dest_dir / year / dest_subdir / "1_DRIVE"
                        logger.info(f"Using year prefix: {year} for path: {dest_subdir}")
                    except Exception as e:
                        logger.error(f"Error creating path with year prefix: {e}")
                        # Fallback to standard path without year prefix
                        target_dir = self.dest_dir / dest_subdir / "1_DRIVE"
                else:
                    # If no year found, use the standard path
                    target_dir = self.dest_dir / dest_subdir / "1_DRIVE"
                    logger.warning(f"No valid year found in path: {dest_subdir}, using standard path")
            else:
                # Standard path without year prefix
                target_dir = self.dest_dir / dest_subdir / "1_DRIVE"
            
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
                    target_file = target_dir / file_path.name
                    shutil.copy2(file_path, target_file)
                    
                    # Record the copied file with timestamp
                    timestamp = datetime.now()
                    self.copied_files[str(file_path)] = {
                        'destination': str(target_file),
                        'timestamp': timestamp.isoformat(),
                        'size': file_path.stat().st_size
                    }
                    
                    # Save history after each copy
                    self.save_history()
                    
                    logger.info(f"Copied: {file_path.name} to {target_dir}/")
        
        except Exception as e:
            logger.error(f"Error processing {directory}: {str(e)}")
    
    def scan_all(self):
        """Scan all directories for .turbosort files."""
        logger.info(f"Scanning for .turbosort files...")
        
        # Walk through all subdirectories
        for root, _, _ in os.walk(self.source_dir):
            self.process_directory(Path(root))
    
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


class FileChangeHandler(FileSystemEventHandler):
    """Handles file system events."""
    
    def __init__(self, sorter):
        self.sorter = sorter
        super().__init__()
    
    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            path = Path(event.src_path)
            
            # If a .turbosort file is created, process its directory
            if path.name == TURBOSORT_FILE:
                logger.info(f"New .turbosort file detected: {path}")
                self.sorter.process_directory(path.parent)
    
    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            path = Path(event.src_path)
            
            # If a .turbosort file is modified, process its directory
            if path.name == TURBOSORT_FILE:
                logger.info(f"Modified .turbosort file detected: {path}")
                self.sorter.process_directory(path.parent)


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
    args = parser.parse_args()
    
    # Initialize the sorter
    sorter = TurboSorter()
    
    # If --history is specified, just display history and exit
    if args.history:
        display_history(sorter, args.detailed)
        return
    
    # Otherwise, proceed with normal operation
    # Do an initial scan
    sorter.scan_all()
    
    # Print initial stats
    if sorter.get_copy_stats()['total_files'] > 0:
        print_stats(sorter)
    
    # Set up the file watcher
    event_handler = FileChangeHandler(sorter)
    observer = Observer()
    observer.schedule(event_handler, SOURCE_DIR, recursive=True)
    observer.start()
    
    try:
        logger.info("TurboSort running. Press Ctrl+C to stop.")
        
        # Periodically print statistics (every 5 minutes)
        last_stats_time = time.time()
        
        while True:
            time.sleep(1)
            
            # Print stats every 5 minutes if files have been copied
            current_time = time.time()
            if current_time - last_stats_time >= 300:  # 5 minutes in seconds
                if sorter.get_copy_stats()['total_files'] > 0:
                    print_stats(sorter)
                last_stats_time = current_time
                
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