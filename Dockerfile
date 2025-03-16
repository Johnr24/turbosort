FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY turbosort.py .

# Create source and destination directories
RUN mkdir -p source destination history

# Set environment variables
ENV SOURCE_DIR=/app/source
ENV DEST_DIR=/app/destination
ENV HISTORY_DIR=/app/history

# S3 is disabled by default - enable via environment variables
ENV USE_S3_SOURCE=false
ENV S3_ENDPOINT=http://minio:9000
ENV S3_BUCKET=turbosort-source
ENV S3_POLL_INTERVAL=30

# Define volumes to persist data
# When using S3, the source volume isn't needed but still defined for compatibility
VOLUME ["/app/source", "/app/destination", "/app/history"]

# Run the application
CMD ["python", "turbosort.py"] 