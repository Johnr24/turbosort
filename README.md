# TurboSort

A simple file sorting system that watches directories and automatically sorts files based on `.turbosort` files.

## How It Works

1. In any subdirectory of the `source` folder, create a `.turbosort` file
2. In this file, write the destination path (e.g., `documents/work`)
3. All files in that directory will be copied to that path in the `destination` folder
4. Changes are detected automatically - no need to run the script again when adding files

## Features

- Super simple `.turbosort` files - just contain the destination directory name
- File change detection - automatically processes directories when changes occur
- Configurable source and destination directories
- Detailed logging of all copy operations

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

### Docker Method

1. Build and start the container using Docker Compose:
   ```
   docker-compose up -d
   ```

2. To stop the container:
   ```
   docker-compose down
   ```

3. Alternatively, run with Docker directly:
   ```
   docker build -t turbosort .
   docker run -d --name turbosort \
     -v $(pwd)/source:/app/source \
     -v $(pwd)/destination:/app/destination \
     turbosort
   ```

4. Put a `.turbosort` file in any directory under the `source` folder
   - Files will be sorted to the corresponding path in the `destination` folder

## Customizing

If you want to change the source or destination directories, edit the constants at the top of the `turbosort.py` file:

```python
SOURCE_DIR = 'source'
DEST_DIR = 'destination'
TURBOSORT_FILE = '.turbosort'
```

When using Docker, you can modify these directories by:
1. Changing the environment variables in `docker-compose.yml`
2. Adjusting the volume mappings to match your local directories 