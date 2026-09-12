#!/usr/bin/env bash
# dev-start.sh — Development process reference for the SDUI project.
#
# This script is NOT an orchestrator — it does not start processes for you.
# It documents exactly what to run and where, since we use tmux/terminal tabs
# instead of Docker Compose.
#
# Usage: read this file and run each command in a separate terminal pane.
# Recommended layout: 5 panes (tmux or Windows Terminal tabs).
#
# Pre-requisites (WSL2 Ubuntu):
#   sudo systemctl start postgresql
#   sudo systemctl start redis-server
#
# Pre-requisites (Windows):
#   cd C:\Users\91805\OneDrive\Desktop\sdui
#   .\venv\Scripts\Activate.ps1

set -euo pipefail

PROJECT_ROOT="/mnt/c/Users/91805/OneDrive/Desktop/sdui"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"   # WSL2 path — install a separate venv here if needed

echo "========================================================"
echo "  SDUI Dev Stack — process reference"
echo "========================================================"
echo ""
echo "PANE 1 — Django dev server (run in PowerShell on Windows)"
echo "  cd C:\\Users\\91805\\OneDrive\\Desktop\\sdui"
echo "  .\\venv\\Scripts\\Activate.ps1"
echo "  python manage.py runserver"
echo ""
echo "PANE 2 — Celery worker (run in WSL2)"
echo "  cd /mnt/c/Users/91805/OneDrive/Desktop/sdui"
echo "  source ~/.venv-sdui/bin/activate"
echo "  celery -A config worker -l info"
echo ""
echo "PANE 3 — Celery beat (run in WSL2, needed from Phase 5 onward)"
echo "  cd /mnt/c/Users/91805/OneDrive/Desktop/sdui"
echo "  source ~/.venv-sdui/bin/activate"
echo "  celery -A config beat -l info"
echo ""
echo "PANE 4 — Redis & Postgres (WSL2 services)"
echo "  sudo service postgresql start"
echo "  sudo service redis-server start"
echo "  # Verify: redis-cli ping  → should return PONG"
echo ""
echo "PANE 5 — Prometheus (WSL2, Phase 7 onward)"
echo "  cd ~/prometheus"
echo "  ./prometheus --config.file=prometheus.yml"
echo ""
echo "========================================================"
echo "  Useful verification commands"
echo "========================================================"
echo ""
echo "DB:    psql -h 127.0.0.1 -p 5433 -U sdui_user -d sdui_dev"
echo "Redis: redis-cli ping"
echo "HTTP:  curl http://localhost:8000/metrics"
echo ""
