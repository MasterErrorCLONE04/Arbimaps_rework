# Use Python 3.10 slim as base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV APP_HOME /app

# Set working directory
WORKDIR $APP_HOME

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
# Note: I'm creating a new requirements.txt inside the backend directory
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
# We use 0.0.0.0 to make it accessible outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
