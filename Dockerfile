FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py run_pipeline.py validate_data.py ./
COPY data/ data/
COPY analysis/ analysis/
COPY api/ api/
COPY app/ app/

# Create directories for models and data output
RUN mkdir -p models data

EXPOSE 5000 8501

# Default: run the API server
CMD ["python", "api/server.py"]
