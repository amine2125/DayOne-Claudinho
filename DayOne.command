#!/bin/bash
# Double-cliquer sur ce fichier pour lancer DayOne. Fermer cette fenêtre arrête tout.
#
# Démarre, sur cette machine : Ollama (modèle local), l'API (port 8000, base chiffrée), le tableau de bord
# (port 5173), l'agent WhatsApp (port 8001, si whatsapp-bot/.env existe) et le banc de test Streamlit (8501).
# Journaux : logs/*.log
cd "$(dirname "$0")" || exit 1
ROOT=$(pwd)
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
mkdir -p logs
PIDS=()
trap 'for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done' EXIT

if [ ! -x .venv/bin/uvicorn ]; then
  echo "Environnement Python incomplet : voir README.md (Installation)."
  read -r -p "Appuyer sur Entrée pour fermer."
  exit 1
fi

# --- Ollama (modèle local, aucune connexion externe) ---
OLLAMA=$(command -v ollama || ls "$HOME/.local/ollama/ollama" /Applications/Ollama.app/Contents/Resources/ollama 2>/dev/null | head -1)
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  if [ -n "$OLLAMA" ]; then
    echo "Démarrage d'Ollama…"
    "$OLLAMA" serve >logs/ollama.log 2>&1 &
    PIDS+=($!)
    for _ in $(seq 1 20); do curl -s http://127.0.0.1:11434/api/version >/dev/null && break; sleep 0.5; done
  else
    echo "Ollama introuvable : l'installer (https://ollama.com), il est nécessaire pour lire les fiches."
  fi
fi

# Modèle de lecture : téléchargé une seule fois (~3,3 Go), ensuite tout reste local.
MODEL="${DAYONE_MODEL:-qwen3-vl:4b-instruct}"
if [ -n "$OLLAMA" ] && ! "$OLLAMA" list 2>/dev/null | grep -q "^$MODEL"; then
  echo "Premier lancement : téléchargement du modèle $MODEL…"
  "$OLLAMA" pull "$MODEL"
fi

# Modèles de lecture du texte (PaddleOCR : détection, latin, arabe) : téléchargés une seule fois (~20 Mo).
if ! .venv/bin/python -c "from dayone.ocr import models_ready; raise SystemExit(not models_ready())"; then
  echo "Premier lancement : téléchargement des modèles OCR (français, anglais, arabe)…"
  .venv/bin/python -m dayone.ocr --download >/dev/null 2>&1 || echo "Téléchargement OCR impossible : connexion internet nécessaire la première fois."
fi

# --- Clé de l'API : créée une fois, gardée dans .api_key (jamais commitée) ---
if [ ! -s .api_key ]; then
  .venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))" > .api_key
  chmod 600 .api_key
fi
export DAYONE_API_KEY=$(cat .api_key)

# --- API (base chiffrée, lecture des photos) : seulement sur cette machine ---
echo "API : http://127.0.0.1:8000"
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 >logs/api.log 2>&1 &
PIDS+=($!)

# --- Agent WhatsApp : seulement s'il est configuré ---
if [ -f whatsapp-bot/.env ]; then
  echo "Agent WhatsApp : http://127.0.0.1:8001 (exposer ce port avec un tunnel : voir whatsapp-bot/README.md)"
  (cd whatsapp-bot && OUR_API_KEY="$DAYONE_API_KEY" DAYONE_API_URL=http://127.0.0.1:8000 \
    "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8001 >"$ROOT/logs/bot.log" 2>&1) &
  PIDS+=($!)
else
  echo "Agent WhatsApp non lancé : créer whatsapp-bot/.env (modèle : whatsapp-bot/.env.example)."
fi

# --- Tableau de bord ---
if command -v npm >/dev/null; then
  if [ ! -d web/node_modules ]; then
    echo "Premier lancement : installation du tableau de bord…"
    (cd web && npm ci --no-audit --no-fund >"$ROOT/logs/web-install.log" 2>&1)
  fi
  echo "Tableau de bord : http://localhost:5173"
  (cd web && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort >"$ROOT/logs/web.log" 2>&1) &
  PIDS+=($!)
  DASHBOARD=http://localhost:5173
else
  echo "Node.js introuvable : tableau de bord non lancé (voir README.md, Installation)."
fi

# --- Banc de test (import d'une photo, comparaison à la référence) ---
echo "Banc de test : http://localhost:8501"
.venv/bin/streamlit run app.py --server.headless true >logs/streamlit.log 2>&1 &
PIDS+=($!)

for _ in $(seq 1 30); do curl -s http://127.0.0.1:8000/health >/dev/null && break; sleep 0.5; done
(sleep 3 && open "${DASHBOARD:-http://localhost:8501}") &
echo
echo "DayOne tourne. Fermer cette fenêtre (ou Ctrl+C) arrête tout."
wait
