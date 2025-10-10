# Kuzuk Docker Environment
# Provides a complete testing environment with KuzuDB and all dependencies

FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    curl \
    pkg-config \
    libssl-dev \
    libffi-dev \
    libc6-dev \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy the entire project first
COPY . .

# Install Python dependencies and the package
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements-dev.txt && \
    pip install aiohttp>=3.8.0 && \
    pip install -e .

# Create directories for test databases
RUN mkdir -p /tmp/kuzu_test_dbs /tmp/kuzu_replicas

# Set proper permissions
RUN chmod +x tests/run_tests.py

# Expose port for mock HTTP services
EXPOSE 8080-8090

# Default command runs the test suite
CMD ["python", "tests/run_tests.py", "--all"]