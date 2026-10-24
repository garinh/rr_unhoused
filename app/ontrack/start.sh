#!/usr/bin/env bash
set -e

echo ""
echo " =========================================="
echo "  NorthByNorthwest (NXNW)"
echo "  Continuum of Care Master Data Engine"
echo "  Rogue River Valley"
echo " =========================================="
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo " [ERROR] python3 not found."
    echo " Please install Python 3.10 or later from https://www.python.org/downloads/"
    exit 1
fi

echo " [1/2] Checking dependencies..."
python3 -m pip install -r requirements.txt --quiet

echo " [2/2] Starting NXNW app..."
echo " Your browser will open automatically to: http://localhost:8501"
echo ""

# Open browser after a short delay (macOS: open, Linux: xdg-open)
(sleep 2 && open "http://localhost:8501" 2>/dev/null || xdg-open "http://localhost:8501" 2>/dev/null || true) &

python3 -m streamlit run app.py --server.headless true --server.port 8501
