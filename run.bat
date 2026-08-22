@echo off
REM Convenience launcher for the job scraper (uses uv).
REM Usage:
REM   run.bat daily
REM   run.bat range 7
REM   run.bat source hnhiring
REM   run.bat status
REM   run.bat list-sources
REM   run.bat test
setlocal
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv is not installed. >&2
    echo Install from https://docs.astral.sh/uv/ >&2
    exit /b 1
)

uv sync --quiet

if "%1"=="" (
    uv run python -m scraper.cli daily
    goto :eof
)
if "%1"=="daily" (
    uv run python -m scraper.cli daily
    goto :eof
)
if "%1"=="range" (
    if "%2"=="" (
        echo Usage: run.bat range ^<days^>
        exit /b 1
    )
    uv run python -m scraper.cli range --days %2
    goto :eof
)
if "%1"=="source" (
    if "%2"=="" (
        echo Usage: run.bat source ^<name^>
        exit /b 1
    )
    uv run python -m scraper.cli source %2 %3 %4
    goto :eof
)
if "%1"=="status" (
    uv run python -m scraper.cli status
    goto :eof
)
if "%1"=="list-sources" (
    uv run python -m scraper.cli list-sources
    goto :eof
)
if "%1"=="test" (
    uv run python -m scraper.cli test
    goto :eof
)

echo Unknown command: %1
echo Usage: run.bat [daily^|range ^<days^>^|source ^<name^>^|status^|list-sources^|test]
exit /b 1
