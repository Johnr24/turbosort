FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY turbosort.py .
COPY file_copier.py .

# Create source and destination directories
RUN mkdir -p source destination

# Set environment variables
ENV SOURCE_DIR=/app/source
ENV DEST_DIR=/app/destination

# Define volumes to persist data
VOLUME ["/app/source", "/app/destination"]

# Run the application
CMD ["python", "turbosort.py"] 