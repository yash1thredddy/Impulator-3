@echo off
REM IMPULATOR Startup Script for Windows
REM Quick start script for local development and production

echo.
echo ============================================
echo    IMPULATOR - Startup Script (Windows)
echo ============================================
echo.

REM Check if Docker is available
where docker >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set DOCKER_AVAILABLE=1
) else (
    set DOCKER_AVAILABLE=0
)

echo Select startup mode:
echo 1) Docker (recommended for production)
echo 2) Local (for development)
echo.

set /p choice="Enter choice [1-2]: "

if "%choice%"=="1" goto docker_start
if "%choice%"=="2" goto local_start
echo Invalid choice. Please run again and select 1 or 2.
goto end

:docker_start
    if %DOCKER_AVAILABLE%==0 (
        echo ERROR: Docker is not installed or not in PATH
        echo Please install Docker Desktop for Windows
        goto end
    )

    echo.
    echo Starting with Docker Compose...
    echo.

    REM Stop existing containers
    echo Stopping existing containers (if any)...
    docker-compose down 2>nul

    REM Build and start
    echo Building and starting containers...
    docker-compose up -d --build

    REM Wait for startup
    echo Waiting for application to start...
    timeout /t 5 /nobreak >nul

    REM Show status
    echo.
    echo Container Status:
    docker-compose ps

    echo.
    echo ========================================
    echo  IMPULATOR is running!
    echo  Access at: http://localhost:8501
    echo ========================================
    echo.
    echo Useful commands:
    echo   View logs:     docker-compose logs -f
    echo   Stop:          docker-compose down
    echo   Restart:       docker-compose restart
    echo.

    goto end

:local_start
    echo.
    echo Starting locally without Docker...
    echo.

    REM Check if virtual environment exists
    if not exist "venv\" (
        echo Creating virtual environment...
        python -m venv venv
        call venv\Scripts\activate.bat
        echo Installing dependencies...
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    ) else (
        echo Virtual environment found
        call venv\Scripts\activate.bat
    )

    REM Create results directory
    if not exist "analysis_results\" mkdir analysis_results

    REM Start Streamlit
    echo Starting Streamlit server...
    streamlit run app.py --server.port=8501 --server.address=localhost

    goto end

:end
    echo.
    pause
