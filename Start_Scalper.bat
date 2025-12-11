@echo off
REM Options Scalper Launcher
REM Fast scalping with smart trailing stops

echo ========================================
echo   OPTIONS SCALPER
echo   Smart Trailing Stops + Reversals
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

REM Check .env
if not exist ".env" (
    echo WARNING: .env file not found!
    copy .env.template .env
    echo Please edit .env with your IBKR credentials
    pause
    exit /b 1
)

echo Starting Options Scalper...
echo.
echo Strategy: Fast Calls/Puts
echo Features:
echo   - Smart trailing stops
echo   - Auto profit booking
echo   - Can reverse positions
echo   - 50+ trades per day capability
echo.
echo Press Ctrl+C to stop
echo.

python options_scalper.py

echo.
echo Scalper stopped.
pause
