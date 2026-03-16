#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Installing dependencies..."
pip install -r requirements.txt -q
pip install -r web/requirements.txt -q

echo ""
echo "============================================================"
echo "  BenefitsNavigator Web UI"
echo "  Open http://localhost:8000 in your browser"
echo "============================================================"
echo ""

python web/server.py
