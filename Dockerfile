FROM python:3.11-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Verify ffmpeg is installed
RUN which ffmpeg && ffmpeg -version

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Start application
CMD gunicorn app:app --timeout 600 --workers 2 --bind 0.0.0.0:$PORT