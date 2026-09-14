#!/usr/bin/env bash
# Arranca la app en tu computador. Doble clic no sirve: ábrelo desde Terminal con:  bash run.sh
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creando entorno (solo la primera vez)…"
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo ""
echo "Listo. Abre en tu navegador:  http://localhost:8000"
echo "Para parar: Ctrl + C"
echo ""
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
