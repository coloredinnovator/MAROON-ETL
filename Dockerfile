# MAROON-ETL Pipeline Container
# Lightweight Python 3.9 image for stateless batch execution
FROM python:3.9-slim

LABEL maintainer="Maroon Technologies"
LABEL description="MAROON-ETL: Stateless batch ETL pipeline for the Maroon data lake"

# Set working directory
WORKDIR /app

# Install system dependencies (minimal)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY vendor/ ./vendor/

# Set Python path
ENV PYTHONPATH=/app/src:/app/vendor/shafanna

# Default: run full pipeline
ENTRYPOINT ["python", "-m", "maroon_etl"]
CMD ["run"]
