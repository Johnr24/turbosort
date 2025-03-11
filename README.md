# TurboSort

A simple file sorting system that watches directories and automatically sorts files based on `.turbosort` files.

## How It Works

1. In any subdirectory of the `source` folder, create a `.turbosort` file
2. In this file, write the destination path (e.g., `documents/work`)
3. All files in that directory will be copied to that path in the `destination` folder, under an `incoming` subdirectory (or your custom suffix if configured)
   - For example, if `.turbosort` contains `documents/work`, files will be copied to `destination/documents/work/incoming/`
   - This suffix is customizable and can be disabled completely (see Configuration)
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

- Docker (for container deployment)

## Usage


### Viewing Copy History

TurboSort tracks file copying activity. To view this history:

```
# Display a simple table of copied files
python turbosort.py --history

# Display detailed information about copied files
python turbosort.py --history --detailed
```

### Docker Method

The recommended way to run TurboSort is using Docker Compose with our pre-built image.

1. Create a `docker-compose.yml` file:
   ```yaml
   version: '3'
   services:
     turbosort:
       image: turbosort/turbosort:latest
       container_name: turbosort
       restart: unless-stopped
       volumes:
         - ./source:/app/source
         - ./destination:/app/destination
         - ./turbosort_history.json:/app/turbosort_history.json
       environment:
         - SOURCE_DIR=/app/source
         - DEST_DIR=/app/destination
         - ENABLE_DRIVE_SUFFIX=true
         - DRIVE_SUFFIX=incoming
         - ENABLE_YEAR_PREFIX=false
   ```

2. Copy the `.env.template` file to `.env` and customize the environment variables:
   ```
   cp .env.template .env
   # Edit .env with your preferred text editor to set your environment variables
   ```

3. Start the container:
   ```
   docker compose up -d
   ```

4. To stop the container:
   ```
   docker compose down
   ```

5. View logs:
   ```
   docker compose logs -f turbosort
   ```

6. Put a `.turbosort` file in any directory under the `source` folder
   - Files will be sorted to the corresponding path in the `destination` folder

7. Run commands inside the container:
   ```
   # View file history
   docker compose exec turbosort python turbosort.py --history
   
   # Clear history
   docker compose exec turbosort python turbosort.py --clear-history
   ```

## Customizing

You can customize TurboSort's behavior using environment variables:

```yaml
environment:
  # Core directory settings
  - SOURCE_DIR=/app/source
  - DEST_DIR=/app/destination
  - HISTORY_FILE=/app/turbosort_history.json
  
  # Drive suffix settings
  - ENABLE_DRIVE_SUFFIX=true
  - DRIVE_SUFFIX=incoming
  
  # Year prefix settings  
  - ENABLE_YEAR_PREFIX=false
  
  # Force recopy mode
  - FORCE_RECOPY=false
```

When using Docker, you can modify the mounted directories by:
1. Changing the environment variables in your `docker-compose.yml` file
2. Adjusting the volume mappings to match your local directories

## Copy History

TurboSort keeps track of all copied files in a JSON file (`turbosort_history.json` by default). This history includes:

- Original source path
- Destination path
- Timestamp of when the file was copied
- File size

This history persists between program runs, allowing you to see a complete record of all file operations.

### File Transfer Tracking

TurboSort operates with a strict "one and done" philosophy:

- Files are uniquely identified by the combination of:
  - The file's contents and attributes (size, modification time)
  - AND its source folder location
- This means identical files in different source folders are treated as different files

Once a file is copied to its destination, it's marked as "processed" in the history. TurboSort will NEVER copy that file again, even if:
- The destination file is deleted
- The destination directory is deleted
- TurboSort is restarted
- The `.turbosort` file is modified

The only exception is if the source file itself changes (modification time or size) while remaining in the same source folder.

This means you can safely delete files from destination directories without worrying about TurboSort re-copying them. TurboSort will only copy a file once, and then completely ignore it forever (unless you explicitly request a re-copy).

#### Cleaning Up History

When you delete files from the source directory, TurboSort automatically removes them from its history on the next scan. If you're experiencing issues with stale history entries, you can manually clear the history with:

```
python turbosort.py --clear-history
```

For Docker installations:
```
docker compose exec turbosort python turbosort.py --clear-history
```

This will remove all history entries and start fresh. TurboSort will then re-process any files found in the source directories.

#### Force Re-copy Mode

If you need to force TurboSort to re-process all files regardless of history, you can enable the `FORCE_RECOPY` option:

```
FORCE_RECOPY=true
```

When this option is enabled:
- All files will be re-copied to their destinations, even if they've been processed before
- History will still be updated with the new transfers
- This is useful when you want to refresh all files or rebuild a destination directory

To return to normal operation, set `FORCE_RECOPY=false` and restart TurboSort.

## Year Prefix Feature

TurboSort supports an optional feature to extract years from the `.turbosort` path and use them as prefixes in the destination structure.

### How it Works

When enabled:
1. TurboSort will look for a 4-digit year (1900-2099) in the path specified in the `.turbosort` file
2. If a year is found, it will be used as a prefix in the destination path
3. The resulting structure will be: `DESTINATION_DIR/YEAR/TURBOSORT_PATH/incoming/`

This is useful for organizing projects by year while maintaining the internal path structure.

### Configuration

To enable this feature, set the `ENABLE_YEAR_PREFIX` environment variable to `true`:

```
ENABLE_YEAR_PREFIX=true
```

You can set this in your `.env` file or in the environment section of your `docker-compose.yml` file.

### Drive Suffix Feature

By default, TurboSort appends an "incoming" suffix to all destination paths. This feature can now be controlled with two environment variables:

- `ENABLE_DRIVE_SUFFIX`: Set to `true` to enable the feature (enabled by default), or `false` to disable it
- `DRIVE_SUFFIX`: The custom suffix to use when the feature is enabled (defaults to "incoming")

To configure the drive suffix feature, add these settings to your environment configuration:

```
# Disable the drive suffix feature entirely
ENABLE_DRIVE_SUFFIX=false

# Or customize the suffix 
ENABLE_DRIVE_SUFFIX=true
DRIVE_SUFFIX=my_custom_suffix
```

### Example

If a `.turbosort` file contains:
```
Project/2025/Client/Campaign
```

With `ENABLE_YEAR_PREFIX=true`, files will be sorted to:
```
DESTINATION_DIR/2025/Project/2025/Client/Campaign/incoming/
```

Without year prefix (`ENABLE_YEAR_PREFIX=false`), files would go to:
```
DESTINATION_DIR/Project/2025/Client/Campaign/incoming/
```

With drive suffix disabled (`ENABLE_DRIVE_SUFFIX=false`), files would go to:
```
DESTINATION_DIR/Project/2025/Client/Campaign/
```

With a custom drive suffix (`DRIVE_SUFFIX=ARCHIVE`), files would go to:
```
DESTINATION_DIR/Project/2025/Client/Campaign/ARCHIVE/
```