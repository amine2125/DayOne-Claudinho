"""Interface DayOne : photo d'une fiche quelconque -> champs structurés -> comparaison à la référence.
Interface en français ou en anglais (dayone/i18n.py) ; la fiche peut être en français, arabe ou anglais.

Lancement : double-clic sur DayOne.command (ou .venv/bin/streamlit run app.py).
Rien n'est écrit sur disque : le résultat se télécharge depuis la page.
"""

import json

import cv2
import pandas as pd
import streamlit as st

from dayone import i18n, page, privacy, vlm
from dayone.dataset import load_index, page_path
from dayone.evaluate import annotation_path, compare, load_annotation, summarize
from dayone.extract import THRESHOLD, NotAFormError, extract_page
from dayone.normalize import parse
from dayone.schema import REFERENCE_PAGE_TYPES, STATUSES, make_field

STATUS_COLORS = {"KNOWN": "#b7e4c7", "NEEDS_REVIEW": "#ffd08a", "ILLEGIBLE": "#f4a6a6", "UNKNOWN": "#d5c6f0",
                 "NOT_PROVIDED": "#eeeeee", "NOT_APPLICABLE": "#eeeeee"}

st.set_page_config(page_title="DayOne", layout="wide")

# ---------------- Langue et réglages ----------------
with st.sidebar:
    lang = st.radio("Langue / Language", list(i18n.LANGS), format_func=i18n.LANGS.get, horizontal=True)


def T(key: str, **kw) -> str:
    return i18n.t(lang, key, **kw)


st.title(T("title"))
st.caption(T("caption"))

with st.sidebar:
    st.header(T("settings"))
    model = st.text_input(T("model"), vlm.DEFAULT_MODEL)
    threshold = st.slider(T("threshold"), 0.5, 0.95, THRESHOLD, 0.05)
    ok, why = vlm.available(model)
    if ok:
        st.success(T("ollama_ready"))
    else:
        st.warning(T("ollama_off", why=i18n.message(lang, why)))

# ---------------- Source ----------------
origin = st.radio(T("source"), ["upload", "dev_page"], format_func=T, horizontal=True)
image_bytes, name, dev_row = None, "", None
if origin == "upload":
    up = st.file_uploader(T("uploader"), type=["png", "jpg", "jpeg"])
    if up:
        image_bytes, name = up.getvalue(), up.name
else:
    rows = load_index("dev")  # jamais le split test
    labels = [T("page_label", n=r["page_number"], p=r["patient"], t=r["page_type"].replace("_", " ")) for r in rows]
    i = st.selectbox(T("page"), range(len(rows)), format_func=lambda k: labels[k])
    dev_row = rows[i]
    image_bytes, name = page_path(dev_row).read_bytes(), f"page {dev_row['page_number']}"

if st.button(T("read"), type="primary", disabled=image_bytes is None):
    with st.status(T("reading"), expanded=True) as status:
        try:
            pred = extract_page(image_bytes, model=model, threshold=threshold, source_name=name,
                                progress=lambda m: st.write(i18n.message(lang, m)))
            status.update(label=T("done", s=pred["timings"]["total_s"]), state="complete")
            # Seule l'image masquée (nom, CIN, téléphone, adresse en noir) reste dans la session.
            view = privacy.redact(page.prepare(page.load_image(image_bytes)), pred["zones_masquees"])
            st.session_state.update(pred=pred, image=view, dev_row=dev_row)
        except NotAFormError as e:
            status.update(label=T("refused"), state="error")
            st.error(i18n.message(lang, str(e)))
        except (RuntimeError, ValueError) as e:
            status.update(label=T("failed"), state="error")
            st.error(i18n.message(lang, str(e)))

pred = st.session_state.get("pred")
if not pred:
    st.info(T("start"))
    st.stop()

# ---------------- Résultat ----------------
st.subheader(pred["title"] or T("untitled"))
counts = pd.Series([f["status"] for f in pred["fields"]], dtype=str).value_counts()
cols = st.columns(len(STATUSES))
for col, s in zip(cols, STATUSES):
    col.metric(i18n.STATUS[lang][s], int(counts.get(s, 0)))
if pred["ignores"]["personnels"]:
    st.caption(T("personal_ignored", n=pred["ignores"]["personnels"]))

left, right = st.columns([2, 3])
with left:
    st.image(cv2.cvtColor(st.session_state["image"], cv2.COLOR_BGR2RGB),
             caption=T("image_caption", n=len(pred["zones_masquees"])))

with right:
    only_review = st.toggle(T("only_review"), value=False)
    table = pd.DataFrame([
        {"id": f["id"], "label": f["label"], "value": "" if f["value"] is None else str(f["value"]),
         "status": f["status"], "confidence": f["confidence"],
         "reason": i18n.REASON[lang].get(f.get("raison"), ""), "read": f.get("valeur_lue", ""),
         "source": f.get("source", "")}
        for f in pred["fields"]
    ], columns=["id", "label", "value", "status", "confidence", "reason", "read", "source"])
    if only_review:
        table = table[table["status"].isin(["NEEDS_REVIEW", "ILLEGIBLE"])]
    edited = st.data_editor(
        # Couleur seulement sur la colonne Statut, avec un texte foncé imposé (lisible en thème clair ou sombre).
        table.style.map(lambda s: f"background-color: {STATUS_COLORS[s]}; color: #111111; font-weight: 600",
                        subset=["status"]),
        column_config={
            "id": None,
            "label": st.column_config.TextColumn(T("col_label")),
            "value": st.column_config.TextColumn(T("col_value")),
            "status": st.column_config.SelectboxColumn(T("col_status"), options=list(STATUSES), required=True),
            "confidence": st.column_config.ProgressColumn(T("col_confidence"), min_value=0, max_value=1,
                                                          format="%.2f"),
            "reason": st.column_config.TextColumn(T("col_reason")),
            "read": st.column_config.TextColumn(T("col_read")),
            "source": st.column_config.TextColumn(T("col_source")),
        },
        disabled=["label", "confidence", "reason", "read", "source"], hide_index=True, height=600, key="editor",
    )
    st.caption(T("edit_help"))


def corrected(pred: dict, edited: pd.DataFrame) -> dict:
    """Applique les corrections humaines du tableau."""
    out = json.loads(json.dumps(pred))
    by_id = {f["id"]: f for f in out["fields"]}
    for _, row in edited.iterrows():
        f = by_id[row["id"]]
        old_value = "" if f["value"] is None else str(f["value"])
        if row["value"] == old_value and row["status"] == f["status"]:
            continue
        status, text = row["status"], (row["value"] or "").strip()
        if f["kind"] == "checkbox":
            value = True if text.lower() in ("true", "x", "oui", "yes") else None
        else:
            value, _ = parse(f["kind"], text) if text else (None, False)
            value = value if value is not None else (text or None)
        if status == "KNOWN" and value is None:
            st.error(T("known_needs_value", label=f["label"]))
            continue
        f.update(make_field(value if status in ("KNOWN", "NEEDS_REVIEW") else None, status, 1.0, source="humain"))
        f.pop("valeur_lue", None)
        f.pop("raison", None)
    return out


final = corrected(pred, edited)
st.download_button(T("download"), json.dumps(final, ensure_ascii=False, indent=1),
                   file_name="fiche.json", mime="application/json")

# ---------------- Comparaison à la référence ----------------
row = st.session_state.get("dev_row")
if row is not None and row["page_type"] in REFERENCE_PAGE_TYPES:
    ann = annotation_path(row["page_number"], row["page_type"])
    ref = load_annotation(ann, row["page_type"]) if ann.exists() else None
    st.subheader(T("reference"))
    if ref is None:
        st.info(T("no_reference", f=ann.name))
    else:
        rows = compare(final, ref, row["page_type"])
        s = summarize(rows)
        m = st.columns(4)
        m[0].metric(T("accuracy"), f"{s['exactitude_globale']:.0%}")
        m[1].metric(T("known_ok"), s["valeurs_connues_justes"])
        m[2].metric(T("to_review"), f"{s['part_a_revoir']:.0%}")
        m[3].metric(T("silent"), s["erreurs_silencieuses"])
        diff = pd.DataFrame([r for r in rows if r["outcome"] != "correct"])
        if len(diff):
            cols = ["field_id", "pred_label", "ref_status", "ref_value", "pred_status", "pred_value", "outcome"]
            st.dataframe(diff[cols].astype(str), hide_index=True)
