#!/bin/bash

# IMPULATOR Startup Script
# Quick start script for local development and production

set -e  # Exit on error

echo "🚀 Starting IMPULATOR..."
echo "================================"

# Function to check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker is not installed. Please install Docker first."
        exit 1
    fi
    echo "✅ Docker found"
}

# Function to check if Docker Compose is installed
check_docker_compose() {
    if ! command -v docker-compose &> /dev/null; then
        echo "❌ Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    echo "✅ Docker Compose found"
}

# Function to start with Docker
start_docker() {
    echo ""
    echo "📦 Starting with Docker Compose..."
    check_docker
    check_docker_compose

    # Stop existing containers
    echo "🛑 Stopping existing containers (if any)..."
    docker-compose down 2>/dev/null || true

    # Build and start
    echo "🔨 Building and starting containers..."
    docker-compose up -d --build

    # Wait for container to be healthy
    echo "⏳ Waiting for application to start..."
    sleep 5

    # Check status
    echo ""
    echo "📊 Container Status:"
    docker-compose ps

    echo ""
    echo "✅ IMPULATOR is running!"
    echo "🌐 Access the application at: http://localhost:8501"
    echo ""
    echo "📝 Useful commands:"
    echo "   View logs:     docker-compose logs -f"
    echo "   Stop:          docker-compose down"
    echo "   Restart:       docker-compose restart"
}

# Function to start locally without Docker
start_local() {
    echo ""
    echo "💻 Starting locally without Docker..."

    # Check if virtual environment exists
    if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
        echo "⚠️  No virtual environment found. Creating one..."
        python3 -m venv venv
        source venv/bin/activate
        echo "📦 Installing dependencies..."
        pip install --upgrade pip
        pip install -r requirements.txt
    else
        echo "✅ Virtual environment found"
        # Activate venv or .venv
        if [ -d "venv" ]; then
            source venv/bin/activate
        else
            source .venv/bin/activate
        fi
    fi

    # Create results directory if it doesn't exist
    mkdir -p analysis_results

    # Start Streamlit
    echo "🚀 Starting Streamlit server..."
    streamlit run app.py --server.port=8501 --server.address=localhost
}

# Main menu
echo "Select startup mode:"
echo "1) Docker (recommended for production)"
echo "2) Local (for development)"
echo ""
read -p "Enter choice [1-2]: " choice

case $choice in
    1)
        start_docker
        ;;
    2)
        start_local
        ;;
    *)
        echo "❌ Invalid choice. Please run again and select 1 or 2."
        exit 1
        ;;
esac
