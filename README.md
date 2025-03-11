# TurboSort

A simple file sorting system that watches directories and automatically sorts files based on `.turbosort` files.

## How It Works

1. In any subdirectory of the `source` folder, create a `.turbosort` file
2. In this file, write the destination path (e.g., `documents/work`)
3. All files in that directory will be copied to that path in the `destination` folder, under a `1_DRIVE` subdirectory
   - For example, if `.turbosort` contains `documents/work`, files will be copied to `destination/documents/work/1_DRIVE/`
4. Changes are detected automatically - no need to run the script again when adding files
5. TurboSort now tracks which files have been copied, when, and where to

## Features

- Super simple `.turbosort` files - just contain the destination directory name
- File change detection - automatically processes directories when changes occur
- Configurable source and destination directories
- Detailed logging of all copy operations
- File copy tracking and history with statistics
- Persistent history saved to a JSON file

## Requirements

- Python 3.6 or higher
- Watchdog library (`pip install watchdog`)

## Usage

### Standard Method

1. Install the required dependency:
   ```
   pip install watchdog
   ```

2. Run the script:
   ```
   python turbosort.py
   ```

3. Put a `.turbosort` file in any directory you want to monitor
   - The content of the file should be the destination path

4. TurboSort will automatically copy files to the right destination

### Viewing Copy History

TurboSort now tracks file copying activity. To view this history:

```
# Display a simple table of copied files
python turbosort.py --history

# Display detailed information about copied files
python turbosort.py --history --detailed
```

### Docker Method

1. Copy the `.env.template` file to `.env` and customize the volume paths:
   ```
   cp .env.template .env
   # Edit .env with your preferred text editor to set your paths
   ```

2. Build and start the container using Docker Compose:
   ```
   docker-compose up -d
   ```

3. To stop the container:
   ```
   docker-compose down
   ```

4. Alternatively, run with Docker directly:
   ```
   docker build -t turbosort .
   docker run -d --name turbosort \
     -v $(pwd)/source:/app/source \
     -v $(pwd)/destination:/app/destination \
     turbosort
   ```

5. Put a `.turbosort` file in any directory under the `source` folder
   - Files will be sorted to the corresponding path in the `destination` folder

## Customizing

If you want to change the source or destination directories, edit the constants at the top of the `turbosort.py` file or set environment variables:

```python
SOURCE_DIR = os.environ.get('SOURCE_DIR', 'source')
DEST_DIR = os.environ.get('DEST_DIR', 'destination')
TURBOSORT_FILE = '.turbosort'
HISTORY_FILE = os.environ.get('HISTORY_FILE', 'turbosort_history.json')
```

When using Docker, you can modify these directories by:
1. Changing the environment variables in `docker-compose.yml`
2. Adjusting the volume mappings to match your local directories 

## Copy History

TurboSort keeps track of all copied files in a JSON file (`turbosort_history.json` by default). This history includes:

- Original source path
- Destination path
- Timestamp of when the file was copied
- File size

This history persists between program runs, allowing you to see a complete record of all file operations.

## Year Prefix Feature

TurboSort supports an optional feature to extract years from the `.turbosort` path and use them as prefixes in the destination structure.

### How it Works

When enabled:
1. TurboSort will look for a 4-digit year (1900-2099) in the path specified in the `.turbosort` file
2. If a year is found, it will be used as a prefix in the destination path
3. The resulting structure will be: `DESTINATION_DIR/YEAR/TURBOSORT_PATH/1_DRIVE/`

This is useful for organizing projects by year while maintaining the internal path structure.

### Configuration

To enable this feature, set the `ENABLE_YEAR_PREFIX` environment variable to `true`:

```
ENABLE_YEAR_PREFIX=true
```

You can set this in your `.env` file or when running the Docker container.

### Example

If a `.turbosort` file contains:
```
Project/2025/Client/Campaign
```

With `ENABLE_YEAR_PREFIX=true`, files will be sorted to:
```
DESTINATION_DIR/2025/Project/2025/Client/Campaign/1_DRIVE/
```

Without year prefix (`ENABLE_YEAR_PREFIX=false`), files would go to:
```
DESTINATION_DIR/Project/2025/Client/Campaign/1_DRIVE/
``` 