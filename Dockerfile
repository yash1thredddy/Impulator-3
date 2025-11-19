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
# Using conda for RDKit installation ensures better compatibility
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create the necessary directories
RUN mkdir -p /app/analysis_results

# Patch rcsbapi to use HTTPS instead of HTTP for schema URLs
RUN python3 patch_rcsbapi.py

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose Streamlit default port
EXPOSE 8501

# Command to run the application
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]