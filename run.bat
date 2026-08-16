@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   📚 ShelfMind - AI Library Assistant Launcher
echo ===================================================
echo.

:: 1. Check for .env file
if not exist .env (
    echo [!] Warning: .env file not found.
    if exist .env.example (
        echo [?] Found .env.example. Creating .env from template...
        copy .env.example .env >nul
        echo [+] Created .env from template.
        echo [!] IMPORTANT: Please open .env and configure your CALIBRE_URL, CALIBRE_USERNAME, CALIBRE_PASSWORD, and GEMINI_API_KEY before running again.
        echo.
        pause
        exit /b
    ) else (
        echo [!] Error: Neither .env nor .env.example was found.
        echo     Please create a .env file with your credentials and API key.
        echo.
        pause
        exit /b
    )
)

:: 2. Check for virtual environment
set "VENV_DIR="
if exist venv\Scripts\activate.bat (
    set "VENV_DIR=venv"
) else if exist .venv\Scripts\activate.bat (
    set "VENV_DIR=.venv"
)

if not defined VENV_DIR (
    echo [?] No Python virtual environment detected [venv/ or .venv/].
    set /p "create_venv=Would you like to create a virtual environment now? (Y/N): "
    if /i "!create_venv!"=="Y" (
        echo [*] Creating virtual environment [venv]...
        python -m venv venv
        if !errorlevel! neq 0 (
            echo [!] Error: Failed to create virtual environment. Make sure Python is installed and on your PATH.
            pause
            exit /b
        )
        set "VENV_DIR=venv"
        echo [+] Virtual environment created successfully.
        
        echo [*] Activating virtual environment...
        call venv\Scripts\activate.bat
        
        echo [*] Installing dependencies from requirements.txt...
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        if !errorlevel! neq 0 (
            echo [!] Error: Failed to install requirements.
            pause
            exit /b
        )
        echo [+] Dependencies installed successfully.
    ) else (
        echo [*] Attempting to run using global Python environment...
    )
) else (
    echo [*] Activating virtual environment [!VENV_DIR!]...
    call !VENV_DIR!\Scripts\activate.bat
)

:: 3. Check if Streamlit is installed
python -c "import streamlit" >nul 2>nul
if !errorlevel! neq 0 (
    echo [!] Error: Streamlit is not installed in the active environment.
    set /p "install_reqs=Would you like to install the required packages now? (Y/N): "
    if /i "!install_reqs!"=="Y" (
        echo [*] Installing dependencies...
        pip install -r requirements.txt
        if !errorlevel! neq 0 (
            echo [!] Error: Failed to install requirements.
            pause
            exit /b
        )
    ) else (
        echo [!] Cannot run the application without Streamlit. Exiting.
        pause
        exit /b
    )
)

:: 4. Run the application
echo [*] Starting Streamlit application...
streamlit run app.py

if !errorlevel! neq 0 (
    echo.
    echo [!] Streamlit application exited with an error.
    pause
)
