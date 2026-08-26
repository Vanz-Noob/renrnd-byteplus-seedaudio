#!/bin/bash
# BytePlus Voice Chat - Start Script
# Usage: ./start.sh

set -e

echo "============================================"
echo "  BytePlus Voice Chat v2.0 - Starting..."
echo "============================================"

# Cek .env
if [ ! -f .env ]; then
    echo "[ERROR] File .env tidak ditemukan!"
    echo "        Jalankan: cp .env.example .env"
    echo "        Lalu isi API keys Anda."
    exit 1
fi

# Cek Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 tidak ditemukan. Install: https://python.org"
    exit 1
fi

# Install dependencies jika belum ada
if [ ! -d "venv" ]; then
    echo "[1/3] Membuat virtual environment..."
    python3 -m venv venv
fi

echo "[2/3] Mengaktifkan virtual environment..."
source venv/bin/activate

echo "[3/3] Install dependencies..."
pip install -q -r requirements.txt

# Tentukan port
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

echo ""
echo "============================================"
echo "  Server: http://localhost:$PORT"
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

# Start server
python -m uvicorn server:app --host "$HOST" --port "$PORT"
