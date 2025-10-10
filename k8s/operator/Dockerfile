FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy operator code
COPY controller.py .
COPY examples/ examples/

# Create non-root user
RUN useradd -r -u 1000 operator && \
    chown -R operator:operator /app

# Switch to non-root user
USER operator

# Health check endpoints
EXPOSE 8080

# Set environment variables
ENV PYTHONPATH=/app
ENV KOPF_LOG_LEVEL=INFO

# Run the operator
CMD ["python", "controller.py"]