FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 deployer && \
    mkdir -p /srv/deployer/{state,work,logs} && \
    chown -R deployer:deployer /srv/deployer

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Change ownership of app directory
RUN chown -R deployer:deployer /app

# Switch to non-root user
USER deployer

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/v1/healthz || exit 1

# Run the application
CMD ["python", "main.py"]
