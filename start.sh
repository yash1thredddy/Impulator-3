#!/bin/bash
# IMPULATOR Start Script
# Starts both FastAPI backend and Streamlit frontend

set -e

# Configuration
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"
export FRONTEND_PORT="${FRONTEND_PORT:-7860}"

echo "=================================================="
echo "Starting IMPULATOR"
echo "=================================================="

# Function to cleanup on exit
cleanup() {
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo "Starting backend on ${API_HOST}:${API_PORT}..."
python -m uvicorn backend.main:app \
    --host $API_HOST \
    --port $API_PORT &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..30}; do
    if curl -s "http://localhost:${API_PORT}/api/v1/health" > /dev/null 2>&1; then
        echo "Backend is ready!"
        break
    fi
    sleep 1
done

# Start frontend
echo "Starting frontend on port ${FRONTEND_PORT}..."
python -m streamlit run frontend/app.py \
    --server.port $FRONTEND_PORT \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
FRONTEND_PID=$!

echo "=================================================="
echo "IMPULATOR is running!"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Backend:  http://localhost:${API_PORT}"
echo "  API Docs: http://localhost:${API_PORT}/docs"
echo "=================================================="

# Wait for processes
wait $BACKEND_PID $FRONTEND_PID
