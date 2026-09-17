#!/usr/bin/env bash
# dev-start.sh -- Development process reference for the SDUI project.
#
# This script is NOT an orchestrator -- it does not start processes for you.
# It documents exactly what to run and where, since this project runs as
# plain native processes, one per tmux/terminal pane (PRD §6).
#
# Usage: read this file and run each command in a separate terminal pane.

set -euo pipefail

echo "========================================================"
echo "  SDUI Dev Stack -- process reference"
echo "========================================================"
echo ""
echo "PANE 1 -- Postgres + Redis"
echo "  sudo service postgresql start"
echo "  sudo service redis-server start"
echo ""
echo "PANE 2 -- Django dev server"
echo "  python manage.py runserver"
echo ""
echo "PANE 3 -- Celery worker"
echo "  celery -A config worker -l info"
echo ""
echo "PANE 4 -- Celery beat"
echo "  celery -A config beat -l info"
echo ""
echo "PANE 5 -- Prometheus"
echo "  ./prometheus --config.file=monitoring/prometheus.yml"
echo ""
echo "PANE 6 -- Grafana"
echo "  sudo service grafana-server start"
echo ""
echo "========================================================"
echo "  Useful verification commands"
echo "========================================================"
echo ""
echo "DB:      psql -U sdui_user -d sdui_dev"
echo "Redis:   redis-cli ping"
echo "Metrics: curl http://localhost:8000/metrics"
echo ""
