"""Interface DayOne : photo d'une page du registre -> champs structurés -> comparaison à la référence.

Lancement : .venv/bin/streamlit run app.py
Rien n'est écrit sur disque : le résultat se télécharge depuis la page.
"""

import json

import cv2
import pandas as pd
import streamlit as st

from dayone import imaging, vlm
from dayone.dataset import load_index, page_path
from dayone.evaluate import annotation_path, compare, load_annotation, summarize
from dayone.extract import THRESHOLD, LayoutError, extract_page
from dayone.normalize import parse
from dayone.schema import STATUSES, V1_PAGE_TYPES, load_schema, make_field

PAGE_TITLES = {pt: load_schema(pt).title for pt in V1_PAGE_TYPES}
STATUS_COLORS = {"KNOWN": "#b7e4c7", "NEEDS_REVIEW": "#ffd08a", "ILLEGIBLE": "#f4a6a6", "UNKNOWN": "#d5c6f0",
                 "NOT_PROVIDED": "#eeeeee", "NOT_APPLICABLE": "#eeeeee"}

st.set_page_config(page_title="DayOne", layout="wide")
st.title("DayOne — lecture du registre")
st.caption("Photo d'une page → champs structurés (valeur, statut, confiance). 100 % local, aucune donnée personnelle extraite.")

# ---------------- Réglages ----------------
with st.sidebar:
    st.header("Réglages")
    model = st.text_input("Modèle local (Ollama)", vlm.DEFAULT_MODEL)
    use_model = st.checkbox("Relire les zones douteuses avec le modèle", value=True)
    threshold = st.slider("Seuil NEEDS_REVIEW", 0.5, 0.95, THRESHOLD, 0.05)
    ok, why = vlm.available(model)
    (st.success if ok else st.warning)(f"Ollama : {'prêt' if ok else why}")

# ---------------- Source ----------------
c1, c2 = st.columns(2)
with c1:
    origin = st.radio("Source", ["Importer une photo", "Page du jeu de développement"], horizontal=True)
    image_bytes, name, dev_row = None, "", None
    if origin == "Importer une photo":
        up = st.file_uploader("Photo ou scan (PNG, JPG)", type=["png", "jpg", "jpeg"])
        if up:
            image_bytes, name = up.getvalue(), up.name
    else:
        rows = [r for r in load_index("dev") if r["page_type"] in V1_PAGE_TYPES]  # jamais le split test
        labels = [f"Page {r['page_number']} — patiente {r['patient']} — {PAGE_TITLES[r['page_type']]}" for r in rows]
        i = st.selectbox("Page", range(len(rows)), format_func=lambda k: labels[k])
        dev_row = rows[i]
        image_bytes, name = page_path(dev_row).read_bytes(), f"page {dev_row['page_number']}"
with c2:
    choice = st.selectbox("Type de page", ["Détection automatique"] + list(V1_PAGE_TYPES),
                          format_func=lambda k: PAGE_TITLES.get(k, k))
    page_type = None if choice == "Détection automatique" else choice
    run = st.button("Lire la page", type="primary", disabled=image_bytes is None)

if run:
    with st.status("Lecture en cours…", expanded=True) as status:
        try:
            pred = extract_page(image_bytes, page_type=page_type, use_model=use_model, model=model,
                                threshold=threshold, source_name=name,
                                progress=st.write)
            status.update(label=f"Terminé en {pred['timings']['total_s']} s", state="complete")
            st.session_state.update(pred=pred, image=image_bytes, dev_row=dev_row)
        except (LayoutError, RuntimeError, ValueError) as e:
            status.update(label="Échec", state="error")
            st.error(str(e))

pred = st.session_state.get("pred")
if not pred:
    st.info("Choisir une page puis cliquer sur « Lire la page ».")
    st.stop()

# ---------------- Résultat ----------------
schema = load_schema(pred["page_type"])
st.subheader(f"{schema.title} — mode {pred['mode']}")
if pred["mode"] == "modele_seul":
    st.warning("Mise en page non reconnue : le modèle a lu la page seul. Tous les champs sont à vérifier.")
counts = pd.Series([f["status"] for f in pred["fields"].values()]).value_counts()
cols = st.columns(len(STATUSES))
for col, s in zip(cols, STATUSES):
    col.metric(s, int(counts.get(s, 0)))

left, right = st.columns([2, 3])
with left:
    img = imaging.load_image(st.session_state["image"])
    if pred["mode"] == "gabarit":
        al = imaging.align(img, pred["page_type"])
        view = imaging.masked_preview(imaging.warp(img, al), pred["page_type"])
        st.image(cv2.cvtColor(view, cv2.COLOR_BGR2RGB), caption="Page alignée (zones personnelles masquées)")
    else:
        st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), caption="Image importée")

with right:
    only_review = st.toggle("Seulement les champs à vérifier", value=False)
    table = pd.DataFrame([
        {"id": f.id, "Groupe": f.group, "Champ": f.label,
         "Valeur": "" if pred["fields"][f.id]["value"] is None else str(pred["fields"][f.id]["value"]),
         "Statut": pred["fields"][f.id]["status"], "Confiance": pred["fields"][f.id]["confidence"],
         "Lu sur la page": pred["fields"][f.id].get("valeur_lue", ""),
         "Source": pred["fields"][f.id].get("source", "")}
        for f in schema.fields
    ])
    if only_review:
        table = table[table["Statut"].isin(["NEEDS_REVIEW", "ILLEGIBLE"])]
    edited = st.data_editor(
        # Couleur seulement sur la colonne Statut, avec un texte foncé imposé (lisible en thème clair ou sombre).
        table.style.map(lambda s: f"background-color: {STATUS_COLORS[s]}; color: #111111; font-weight: 600",
                        subset=["Statut"]),
        column_config={
            "id": None,
            "Statut": st.column_config.SelectboxColumn(options=list(STATUSES), required=True),
            "Confiance": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
        },
        disabled=["Groupe", "Champ", "Confiance", "Lu sur la page", "Source"], hide_index=True, height=560,
        key="editor",
    )
    st.caption("Corriger une valeur ou un statut directement dans le tableau : le champ passe en source « humain », "
               "confiance 1. « Lu sur la page » : mot complété par le lexique (lettre accentuée absente de la page).")


def corrected(pred: dict, edited: pd.DataFrame) -> dict:
    """Applique les corrections humaines du tableau."""
    out = json.loads(json.dumps(pred))
    for _, row in edited.iterrows():
        f = schema.field(row["id"])
        old = pred["fields"][f.id]
        old_value = "" if old["value"] is None else str(old["value"])
        if row["Valeur"] == old_value and row["Statut"] == old["status"]:
            continue
        status, text = row["Statut"], (row["Valeur"] or "").strip()
        if f.kind == "checkbox":
            value = True if text.lower() in ("true", "x", "oui") else None
        else:
            value, _ = parse(f.kind, text) if text else (None, False)
            value = value if value is not None else (text or None)
        if status == "KNOWN" and value is None:
            st.error(f"{f.label} : KNOWN exige une valeur.")
            continue
        out["fields"][f.id] = make_field(value if status in ("KNOWN", "NEEDS_REVIEW") else None, status, 1.0,
                                         source="humain")
    return out


final = corrected(pred, edited)
st.download_button("Télécharger le résultat (JSON)", json.dumps(final, ensure_ascii=False, indent=1),
                   file_name=f"{pred['page_type']}.json", mime="application/json")

# ---------------- Comparaison à la référence ----------------
row = st.session_state.get("dev_row")
if row is not None:
    ann = annotation_path(row["page_number"], row["page_type"])
    ref = load_annotation(ann, row["page_type"]) if ann.exists() else None
    st.subheader("Comparaison à la référence")
    if ref is None:
        st.info(f"Pas de référence remplie pour cette page ({ann.name}).")
    else:
        rows = compare(final, ref)
        s = summarize(rows)
        m = st.columns(4)
        m[0].metric("Exactitude", f"{s['exactitude_globale']:.0%}")
        m[1].metric("Valeurs connues justes", s["valeurs_connues_justes"])
        m[2].metric("À revoir", f"{s['part_a_revoir']:.0%}")
        m[3].metric("Erreurs silencieuses", s["erreurs_silencieuses"])
        diff = pd.DataFrame([r for r in rows if r["outcome"] != "correct"])
        if len(diff):
            cols = ["field_id", "ref_status", "ref_value", "pred_status", "pred_value", "outcome"]
            st.dataframe(diff[cols].astype(str), hide_index=True)
