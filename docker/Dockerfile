FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml poetry.lock* ./
COPY src ./src

# Install Poetry and dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-root

# Install the package
RUN poetry install --no-dev

# Create logs directory
RUN mkdir -p logs

# Expose metrics port
EXPOSE 8000

# Run the exporter
CMD ["fritz-monitor", "run", "--host", "0.0.0.0", "--port", "8000"]
