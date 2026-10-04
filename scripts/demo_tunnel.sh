#!/usr/bin/env bash
# Met DayOne en ligne pour une démo, depuis cette machine : l'API et le tableau de bord deviennent
# joignables en HTTPS par des tunnels Cloudflare gratuits (sans compte). Les données restent ici.
#
# Usage : ./scripts/demo_tunnel.sh        (Ctrl+C arrête tout)
# Prérequis : brew install cloudflared ; dépendances Python et `npm install` dans web/ faits.
# Les adresses changent à chaque lancement : donner la nouvelle adresse de l'API au bot WhatsApp
# (DAYONE_API_URL dans whatsapp-bot/.env, puis relancer le bot).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v cloudflared >/dev/null || { echo "cloudflared absent : brew install cloudflared"; exit 1; }
# Python avec PaddleOCR (PaddlePaddle n'existe pas pour Python 3.14) : .venv-ocr s'il existe.
PY=.venv-ocr/bin; [ -x "$PY/uvicorn" ] || PY=.venv/bin
LOGS=$(mktemp -d)
trap 'kill 0 2>/dev/null' EXIT
command -v caffeinate >/dev/null && caffeinate -i -w $$ &    # macOS : pas de mise en veille pendant la démo

tunnel_url() {   # attend l'adresse publique écrite par cloudflared dans son journal
  for _ in $(seq 1 60); do
    url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$1" | head -1 || true)
    [ -n "$url" ] && { echo "$url"; return; }
    sleep 1
  done
  echo "Tunnel non ouvert, voir $1" >&2; exit 1
}

# 1. API (port 8000), sauf si elle tourne déjà
if ! curl -s -m 2 http://localhost:8000/health >/dev/null; then
  "$PY/uvicorn" api.main:app --port 8000 >"$LOGS/api.log" 2>&1 &
  until curl -s -m 2 http://localhost:8000/health >/dev/null; do sleep 1; done
fi

# 2. Tunnel vers l'API
cloudflared tunnel --url http://localhost:8000 >"$LOGS/api_tunnel.log" 2>&1 &
API=$(tunnel_url "$LOGS/api_tunnel.log")

# 3. Tableau de bord construit avec l'adresse publique de l'API, servi en statique (port 4173), puis son tunnel
(cd web && VITE_API_URL="$API" npx vite build >"$LOGS/build.log" 2>&1)
python3 -m http.server 4173 -d web/dist >"$LOGS/web.log" 2>&1 &
cloudflared tunnel --url http://localhost:4173 >"$LOGS/web_tunnel.log" 2>&1 &
WEB=$(tunnel_url "$LOGS/web_tunnel.log")

echo
echo "Tableau de bord : $WEB"
echo "API             : $API   (documentation : $API/docs)"
echo "Bot WhatsApp    : DAYONE_API_URL=$API dans whatsapp-bot/.env, puis relancer le bot"
echo "Journaux        : $LOGS"
echo "Ctrl+C pour tout arrêter."
wait
