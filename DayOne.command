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
    echo "Ollama introuvable : l'application marchera sans le modèle (OCR et cases seulement)."
  fi
fi

trap '[ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null' EXIT

echo "DayOne démarre sur http://localhost:8501 …"
(sleep 3 && open http://localhost:8501) &
.venv/bin/streamlit run app.py
