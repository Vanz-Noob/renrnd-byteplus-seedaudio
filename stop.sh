#!/bin/bash
# BytePlus Voice Chat - Stop Script
# Usage: ./stop.sh

echo "============================================"
echo "  BytePlus Voice Chat - Stopping..."
echo "============================================"

# Cari dan kill proses uvicorn
PIDS=$(pgrep -f "uvicorn server:app" 2>/dev/null || true)

if [ -z "$PIDS" ]; then
    echo "Server tidak berjalan."
    exit 0
fi

for PID in $PIDS; do
    echo "Menghentikan proses PID $PID..."
    kill "$PID" 2>/dev/null || true
done

# Tunggu proses berhenti
sleep 2

# Force kill jika masih berjalan
PIDS=$(pgrep -f "uvicorn server:app" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "Force kill PID $PID..."
        kill -9 "$PID" 2>/dev/null || true
    done
fi

echo "Server berhenti."
