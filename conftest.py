# `pytest` à la racine : tests du moteur (dayone/) et de l'API (api/).
# Le bot WhatsApp a sa propre suite (paquet `app`, qui entrerait en conflit avec app.py) :
#   cd whatsapp-bot && python -m pytest
# scripts/smoke_test.py est un script (nom en *_test.py), pas un test.
collect_ignore = ["whatsapp-bot", "web", "scripts"]
