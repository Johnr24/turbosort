#!/usr/bin/env python3
"""
JSON File Copier

This script scans a source directory for JSON files, and if a JSON file contains
a key with a directory name, it copies the file to that directory in the destination path.
"""

import os
import json
import shutil
import argparse
from pathlib import Path


def scan_and_copy_json_files(source_dir, dest_dir, dir_key_name="directory"):
    """
    Scans source_dir recursively for JSON files, and copies them to dest_dir/[directory_value]
    where [directory_value] is the value of the dir_key_name in the JSON file.
    
    Args:
        source_dir (str): Path to the source directory to scan
        dest_dir (str): Path to the destination directory
        dir_key_name (str, optional): The name of the key in JSON that contains the directory name.
                                     Defaults to "directory".
    """
    source_path = Path(source_dir)
    dest_path = Path(dest_dir)
    
    # Create destination directory if it doesn't exist
    if not dest_path.exists():
        print(f"Creating destination directory: {dest_path}")
        dest_path.mkdir(parents=True, exist_ok=True)
    
    # Track the number of files processed
    files_found = 0
    files_copied = 0
    
    # Walk through the source directory recursively
    for root, _, files in os.walk(source_path):
        for file in files:
            if file.lower().endswith('.json'):
                files_found += 1
                json_file_path = Path(root) / file
                
                try:
                    # Load and parse the JSON file
                    with open(json_file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    
                    # Check if the directory key exists in the JSON
                    if dir_key_name in json_data and isinstance(json_data[dir_key_name], str):
                        directory_value = json_data[dir_key_name]
                        target_dir = dest_path / directory_value
                        
                        # Create the target directory if it doesn't exist
                        if not target_dir.exists():
                            print(f"Creating target directory: {target_dir}")
                            target_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Copy the JSON file to the target directory
                        target_file = target_dir / file
                        shutil.copy2(json_file_path, target_file)
                        print(f"Copied: {json_file_path} -> {target_file}")
                        files_copied += 1
                    else:
                        print(f"No '{dir_key_name}' key found in {json_file_path}, skipping")
                
                except json.JSONDecodeError:
                    print(f"Error: Could not parse JSON file {json_file_path}")
                except Exception as e:
                    print(f"Error processing {json_file_path}: {str(e)}")
    
    print(f"\nSummary:")
    print(f"JSON files found: {files_found}")
    print(f"Files copied: {files_copied}")


def main():
    """Main function to parse arguments and execute the script."""
    parser = argparse.ArgumentParser(description='Copy JSON files based on a directory key.')
    parser.add_argument('source_dir', help='Source directory to scan for JSON files')
    parser.add_argument('dest_dir', help='Destination directory to copy files to')
    parser.add_argument('--key', default='directory', 
                        help='Name of the key in JSON files that contains the directory name (default: "directory")')
    
    args = parser.parse_args()
    
    # Validate directories
    if not os.path.isdir(args.source_dir):
        print(f"Error: Source directory '{args.source_dir}' does not exist or is not a directory")
        return
    
    scan_and_copy_json_files(args.source_dir, args.dest_dir, args.key)


if __name__ == "__main__":
    main() 