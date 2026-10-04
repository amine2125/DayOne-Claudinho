#!/bin/bash
# Double-cliquer sur ce fichier pour lancer DayOne. Fermer cette fenêtre arrête l'application.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/streamlit ]; then
  echo "Environnement Python absent : voir README.md (Installation)."
  read -r -p "Appuyer sur Entrée pour fermer."
  exit 1
fi

# Démarre Ollama s'il ne tourne pas déjà (modèle local, aucune connexion externe).
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  OLLAMA=$(command -v ollama || ls "$HOME/.local/ollama/ollama" /Applications/Ollama.app/Contents/Resources/ollama 2>/dev/null | head -1)
  if [ -n "$OLLAMA" ]; then
    echo "Démarrage d'Ollama…"
    "$OLLAMA" serve >/dev/null 2>&1 &
    OLLAMA_PID=$!
    for _ in $(seq 1 20); do curl -s http://127.0.0.1:11434/api/version >/dev/null && break; sleep 0.5; done
  else
    echo "Ollama introuvable : l'installer (https://ollama.com), il est nécessaire pour lire les fiches."
  fi
fi

trap '[ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null' EXIT

# Modèle de lecture : téléchargé une seule fois (~3,3 Go), ensuite tout reste local.
MODEL="${DAYONE_MODEL:-qwen3-vl:4b-instruct}"
OLLAMA=${OLLAMA:-$(command -v ollama || ls "$HOME/.local/ollama/ollama" /Applications/Ollama.app/Contents/Resources/ollama 2>/dev/null | head -1)}
if [ -n "$OLLAMA" ] && ! "$OLLAMA" list 2>/dev/null | grep -q "^$MODEL"; then
  echo "Premier lancement : téléchargement du modèle $MODEL…"
  "$OLLAMA" pull "$MODEL"
fi

# Modèles de lecture du texte (PaddleOCR : détection, latin, arabe) : téléchargés une seule fois (~20 Mo).
if ! .venv/bin/python -c "from dayone.ocr import models_ready; raise SystemExit(not models_ready())"; then
  echo "Premier lancement : téléchargement des modèles OCR (français, anglais, arabe)…"
  .venv/bin/python -m dayone.ocr --download >/dev/null 2>&1 || echo "Téléchargement OCR impossible : connexion internet nécessaire la première fois."
fi

echo "DayOne démarre sur http://localhost:8501 …"
(sleep 3 && open http://localhost:8501) &
.venv/bin/streamlit run app.py
