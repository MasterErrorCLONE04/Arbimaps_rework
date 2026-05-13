# Use Python 3.10 slim as base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV APP_HOME /app

# Set working directory
WORKDIR $APP_HOME

# Install system dependencies (includes Java JRE for ili2pg and ilivalidator)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    curl \
    unzip \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Install ili2pg 5.1.0 (INTERLIS ↔ PostgreSQL transfer tool)
# Required by: /panel/asignaciones/cargas (assignment workload imports/exports)
# Source: https://github.com/claeis/ili2db
RUN curl -fsSL https://downloads.interlis.ch/ili2pg/ili2pg-5.1.0.zip -o /tmp/ili2pg.zip \
    && mkdir -p /opt/ili2pg \
    && unzip -o /tmp/ili2pg.zip -d /opt/ili2pg \
    && rm /tmp/ili2pg.zip \
    && echo "ili2pg 5.1.0 installed at /opt/ili2pg"

# Install ilivalidator 1.14.1 (INTERLIS XTF/ITF validation tool)
# Required by: /panel/validacion-xtf (XTF file validation)
# Source: https://github.com/claeis/ilivalidator
# Note: Version 1.14.1 matches the iox-ili-1.22.x / ili2c-5.4.x stack used by ili2pg 5.1.0
RUN curl -fsSL https://downloads.interlis.ch/ilivalidator/ilivalidator-1.14.1.zip -o /tmp/ilivalidator.zip \
    && mkdir -p /opt/ilivalidator \
    && unzip -o /tmp/ilivalidator.zip -d /opt/ilivalidator \
    && rm /tmp/ilivalidator.zip \
    && echo "ilivalidator 1.14.1 installed at /opt/ilivalidator"

# Copy requirements file
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
