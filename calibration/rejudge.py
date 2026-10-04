"""Re-note des réponses déjà obtenues (sans rappeler le modèle). Usage : python -m calibration.rejudge RESULTATS.pkl"""
import pickle
import sys

from calibration.evaluate_prompts import judge
from calibration.references import values_in

data = pickle.load(open(sys.argv[1], "rb"))
items = data["items"]
for r in data["results"]:
    v = [judge(a, values_in(c["page"], c["box"], c["shape"])) for a, c in zip(r["answers"], items)]
    n = len(v)
    print(f"{r['prompt']:5} juste {v.count('juste'):3}/{n} ({100 * v.count('juste') / n:4.1f} %) | "
          f"fausse {v.count('fausse'):3} ({100 * v.count('fausse') / n:4.1f} %) | abstention {v.count('abstention')}")
