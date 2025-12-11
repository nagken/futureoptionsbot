@echo off
REM Futures Options Trading Bot Launcher
REM Starts the options bot with proper configuration

echo ========================================
echo   FUTURES OPTIONS BOT LAUNCHER
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist ".env" (
    echo WARNING: .env file not found!
    echo Copying .env.template to .env...
    copy .env.template .env
    echo.
    echo Please edit .env file with your IBKR credentials
    echo Then run this script again.
    pause
    exit /b 1
)

REM Check if required packages are installed
echo Checking dependencies...
pip show ibapi >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install -r requirements.txt
)

echo.
echo Starting Futures Options Bot...
echo.
echo Press Ctrl+C to stop the bot
echo.

REM Run the bot
python futures_options_bot.py

echo.
echo Bot stopped.
pause
