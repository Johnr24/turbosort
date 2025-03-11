#!/usr/bin/env python3
"""
TurboSort - Simple Directory Watcher and File Sorter

Monitors a source directory and sorts files to destination directories
based on .turbosort files.
"""

import os
import time
import shutil
import logging
from pathlib import Path
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


class TurboSorter:
    """Handles sorting files based on .turbosort files."""
    
    def __init__(self):
        """Initialize the TurboSorter with default directories."""
        self.source_dir = Path(SOURCE_DIR)
        self.dest_dir = Path(DEST_DIR)
        
        # Ensure directories exist
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"TurboSort initialized: watching {self.source_dir}")
        logger.info(f"Files will be sorted to {self.dest_dir}")
    
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
            
            # Create the destination directory
            target_dir = self.dest_dir / dest_subdir
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all files except the .turbosort file
            for file_path in directory.iterdir():
                if file_path.is_file() and file_path.name != TURBOSORT_FILE:
                    target_file = target_dir / file_path.name
                    shutil.copy2(file_path, target_file)
                    logger.info(f"Copied: {file_path.name} to {dest_subdir}/")
        
        except Exception as e:
            logger.error(f"Error processing {directory}: {str(e)}")
    
    def scan_all(self):
        """Scan all directories for .turbosort files."""
        logger.info(f"Scanning for .turbosort files...")
        
        # Walk through all subdirectories
        for root, _, _ in os.walk(self.source_dir):
            self.process_directory(Path(root))


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


def main():
    """Main function to run TurboSort."""
    # Initialize the sorter
    sorter = TurboSorter()
    
    # Do an initial scan
    sorter.scan_all()
    
    # Set up the file watcher
    event_handler = FileChangeHandler(sorter)
    observer = Observer()
    observer.schedule(event_handler, SOURCE_DIR, recursive=True)
    observer.start()
    
    try:
        logger.info("TurboSort running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping TurboSort...")
        observer.stop()
    
    observer.join()


if __name__ == "__main__":
    main() 