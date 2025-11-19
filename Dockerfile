FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for RDKit and other visualization libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    libfreetype6-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for HF Spaces (required for security)
RUN useradd -m -u 1000 user

# Copy application code
COPY --chown=user:user . .

# Create the necessary directories with proper permissions
RUN mkdir -p /app/analysis_results && chown -R user:user /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOME=/home/user

# Switch to non-root user
USER user

# Expose Streamlit default port (7860 for HF Spaces)
EXPOSE 7860

# Healthcheck for container monitoring
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import requests; requests.get('http://localhost:7860/_stcore/health')"

# Command to run the application
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]