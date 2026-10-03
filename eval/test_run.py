import io
import json
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from app.pipeline import extract

def test_page(p):
    with open(p, "rb") as f:
        data = f.read()
    resp = extract(data)
    print(f"\n=================== {p} ({resp.layout}) ===================")
    print("Donnees Extraites (JSON Tag - Valeur):")
    print(json.dumps(resp.donnees_extraites, indent=2, ensure_ascii=False))
    if resp.visites_extraites and len(resp.visites_extraites) > 1:
        print(f"Visites Extraites ({len(resp.visites_extraites)} colonnes):")
        for i, v in enumerate(resp.visites_extraites):
            print(f"  [Visite {i+1}]: {v}")

def main():
    pages = [
        "data/Paper Registry/dossiers_specimen_10_patientes-01.png",
        "data/Paper Registry/dossiers_specimen_10_patientes-02.png",
        "data/Paper Registry/dossiers_specimen_10_patientes-03.png",
        "data/Paper Registry/dossiers_specimen_10_patientes-04.png",
        "data/Paper Registry/dossiers_specimen_10_patientes-05.png",
        "data/Paper Registry/dossiers_specimen_10_patientes-06.png",
    ]
    for p in pages:
        test_page(p)

if __name__ == "__main__":
    main()
