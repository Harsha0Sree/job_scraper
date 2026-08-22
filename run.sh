#!/usr/bin/env bash
# Convenience launcher for the job scraper (uses uv).
# Usage:
#   ./run.sh daily              # daily scrape across all sources
#   ./run.sh range 7            # last 7 days
#   ./run.sh range 30           # last 30 days
#   ./run.sh source hnhiring    # only one source
#   ./run.sh status             # show state stats
#   ./run.sh list-sources       # list configured sources
#   ./run.sh test               # smoke test (listings only)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not installed." >&2
    echo "Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

# Ensure dependencies are installed (auto-syncs the .venv)
uv sync --quiet

case "${1:-daily}" in
    daily)
        exec uv run python -m scraper.cli daily "${@:2}"
        ;;
    range)
        if [ $# -lt 2 ]; then
            echo "Usage: $0 range <days>" >&2
            exit 1
        fi
        exec uv run python -m scraper.cli range --days "$2" "${@:3}"
        ;;
    source)
        if [ $# -lt 2 ]; then
            echo "Usage: $0 source <name> [--days N]" >&2
            exit 1
        fi
        exec uv run python -m scraper.cli source "$2" "${@:3}"
        ;;
    status)
        exec uv run python -m scraper.cli status "${@:2}"
        ;;
    list-sources)
        exec uv run python -m scraper.cli list-sources "${@:2}"
        ;;
    test)
        exec uv run python -m scraper.cli test "${@:2}"
        ;;
    *)
        echo "Unknown command: $1" >&2
        echo "Usage: $0 [daily|range <days>|source <name>|status|list-sources|test]" >&2
        exit 1
        ;;
esac
