"""Fiche PDF d'un dossier validé : le résultat final mis en page, lisible et propre (pas la photo manuscrite).

Fabriquée à la demande depuis le résultat final chiffré (store.final_json) : aucun PDF n'est écrit sur
disque. Aucune donnée personnelle : le résultat final n'en contient pas.

Mise en page : en-tête (code patiente, dates), résumé (valeurs lues, à vérifier, corrigées), puis chaque page
du registre, section par section. Les cases d'un tableau du registre (« HTA | Famille de la femme »)
redeviennent un vrai tableau. Français, arabe et anglais (polices Noto, mise en forme de l'arabe par HarfBuzz).
"""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONTS = Path(__file__).resolve().parent / "fonts"

TEAL = (31, 107, 102)
TEAL_SOFT = (234, 243, 242)
INK = (30, 39, 51)
MUTED = (107, 114, 128)
LINE = (226, 229, 233)
REVIEW, REVIEW_SOFT = (180, 83, 9), (254, 243, 199)
EDITED, EDITED_SOFT = (29, 78, 216), (219, 234, 254)

PAGE_NAMES = {"identification_antecedents": "Identification et antécédents", "accouchement": "Accouchement"}
UNITS = {"weight": "g", "length": "cm", "weeks": "SA"}
TO_REVIEW = ("NEEDS_REVIEW", "ILLEGIBLE")
EMPTY = ("NOT_PROVIDED", "NOT_APPLICABLE")


def _date(iso: str | None, with_time: bool = False) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return d.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def value_text(f: dict) -> str:
    """Valeur lisible : « Oui », « 12/11/2022 », « 3250 g », « Inconnu », « Illisible »."""
    status, value, kind = f.get("status"), f.get("value"), f.get("kind", "text")
    if status == "UNKNOWN":
        return "Inconnu"
    if status == "ILLEGIBLE":
        return "Illisible"
    if value is None:
        return "—"
    if value is True:
        return "Oui"
    if isinstance(value, str) and not re.search(r"\w", value):
        return "—"                       # pointillés du formulaire lus comme une valeur
    if kind == "date" and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return _date(value)
    if kind == "sex":
        return {"F": "Féminin", "M": "Masculin"}.get(str(value).upper(), str(value))
    if kind in UNITS and isinstance(value, (int, float)):
        return f"{value} {UNITS[kind]}"
    return str(value)


def _mark(f: dict) -> str:
    if f.get("status") in TO_REVIEW:
        return "review"
    if f.get("origin") in ("CORRECTED", "MANUAL"):
        return "edited"
    return ""


class RecordPDF(FPDF):
    def __init__(self, final: dict):
        super().__init__(format="A4")
        self.final = final
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, margin=18)
        for style, name in (("", "Regular"), ("B", "Bold")):
            self.add_font("Noto", style, str(FONTS / f"NotoSans-{name}.ttf"))
            self.add_font("NotoAr", style, str(FONTS / f"NotoSansArabic-{name}.ttf"))
        self.set_fallback_fonts(["NotoAr"])
        self.set_text_shaping(True)
        self.set_title(f"Dossier {final.get('patient_code', '')}")
        self.set_creator("DayOne")

    # --- cadre de chaque page ---
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Noto", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"DayOne · Dossier {self.final.get('patient_code', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Noto", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "Généré par DayOne · aucune donnée personnelle (nom, CIN, téléphone, adresse) · "
                        f"le registre papier reste la référence", align="L")
        self.set_x(-40)
        self.cell(24, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    # --- blocs ---
    def title_block(self, counts: Counter):
        f = self.final
        w = self.w - self.l_margin - self.r_margin
        self.set_fill_color(*TEAL)
        self.rect(self.l_margin, self.t_margin, w, 34, style="F")
        self.set_xy(self.l_margin + 6, self.t_margin + 5)
        self.set_text_color(255, 255, 255)
        self.set_font("Noto", "", 9)
        self.cell(0, 5, "Registre maternel · fiche validée par la sage-femme")
        self.set_xy(self.l_margin + 6, self.t_margin + 11)
        self.set_font("Noto", "B", 20)
        self.cell(0, 10, f"Patiente {f.get('patient_code') or '—'}")
        self.set_xy(self.l_margin + 6, self.t_margin + 23)
        self.set_font("Noto", "", 9)
        pages = len(f.get("pages", []))
        self.cell(0, 5, f"Capturé le {_date(f.get('captured_at'), True)}  ·  validé le {_date(f.get('validated_at'), True)}"
                        f"  ·  {pages} page{'s' if pages > 1 else ''}")
        self.set_y(self.t_margin + 40)
        chips = [("Valeurs lues", counts["known"], TEAL, TEAL_SOFT), ("À vérifier", counts["review"], REVIEW, REVIEW_SOFT),
                 ("Corrigées / ajoutées", counts["edited"], EDITED, EDITED_SOFT), ("Non renseignées", counts["empty"], MUTED, (243, 244, 246))]
        cw = (w - 3 * 3) / 4
        y = self.get_y()
        for i, (label, n, fg, bg) in enumerate(chips):
            x = self.l_margin + i * (cw + 3)
            self.set_fill_color(*bg)
            self.rect(x, y, cw, 15, style="F", round_corners=True, corner_radius=2)
            self.set_xy(x + 3, y + 1.5)
            self.set_text_color(*fg)
            self.set_font("Noto", "B", 13)
            self.cell(cw - 6, 7, str(n))
            self.set_xy(x + 3, y + 8.5)
            self.set_font("Noto", "", 7.5)
            self.cell(cw - 6, 5, label)
        self.set_y(y + 20)
        self.set_font("Noto", "", 7.5)
        self.set_text_color(*MUTED)
        self.multi_cell(0, 4, f"Dossier {f.get('record_id', '')} · sage-femme {f.get('midwife_id') or '—'}"
                              + (f" · patiente liée le {_date(f.get('linked_at'), True)}" if f.get("linked_at") else ""))
        self.ln(3)

    def page_heading(self, page: dict, i: int, total: int):
        name = PAGE_NAMES.get(page.get("page_type")) or page.get("title") or "Page du registre"
        self.ensure(18)
        self.set_text_color(*TEAL)
        self.set_font("Noto", "B", 13)
        self.cell(0, 8, f"Page {i + 1}/{total} · {name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*TEAL)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def section_heading(self, name: str):
        self.ensure(14)
        self.set_text_color(*INK)
        self.set_font("Noto", "B", 10)
        self.cell(0, 6, name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

    def ensure(self, height: float):
        if self.get_y() + height > self.h - self.b_margin:
            self.add_page()

    def field_rows(self, fields: list[dict]):
        """Étiquette à gauche, valeur à droite ; une ligne teintée si à vérifier ou corrigée."""
        w = self.w - self.l_margin - self.r_margin
        lw = w * 0.45
        for f in fields:
            mark = _mark(f)
            value = value_text(f) + ("  · à vérifier" if mark == "review" else "  · corrigé" if mark == "edited" else "")
            self.set_font("Noto", "", 9)
            lines = max(len(self.multi_cell(lw - 4, 5, f.get("label", ""), dry_run=True, output="LINES")),
                        len(self.multi_cell(w - lw - 4, 5, value, dry_run=True, output="LINES")))
            h = 5 * lines + 2
            self.ensure(h)
            y = self.get_y()
            if mark:
                self.set_fill_color(*(REVIEW_SOFT if mark == "review" else EDITED_SOFT))
                self.rect(self.l_margin, y, w, h, style="F")
            self.set_draw_color(*LINE)
            self.set_line_width(0.2)
            self.line(self.l_margin, y + h, self.l_margin + w, y + h)
            self.set_xy(self.l_margin + 2, y + 1)
            self.set_text_color(*MUTED)
            self.multi_cell(lw - 4, 5, f.get("label", ""))
            self.set_xy(self.l_margin + lw, y + 1)
            self.set_text_color(*(REVIEW if mark == "review" else EDITED if mark == "edited" else INK))
            self.set_font("Noto", "B", 9)
            self.multi_cell(w - lw - 4, 5, value)
            self.set_y(y + h)
        self.ln(2)

    def grid(self, rows: list[str], cols: list[str], cells: dict):
        """Tableau du registre : rangées × colonnes, cases à vérifier en orange, corrigées en bleu."""
        w = self.w - self.l_margin - self.r_margin
        first = min(55.0, w * 0.32)
        cw = (w - first) / len(cols)
        self.ensure(7 * (len(rows) + 1) + 4)
        self.set_font("Noto", "B", 8)
        self.set_fill_color(*TEAL_SOFT)
        self.set_text_color(*TEAL)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.cell(first, 7, "", border=1, fill=True)
        for c in cols:
            self.cell(cw, 7, c, border=1, fill=True, align="C")
        self.ln()
        for r in rows:
            self.set_font("Noto", "B", 8.5)
            self.set_text_color(*INK)
            self.cell(first, 7, r, border=1)
            self.set_font("Noto", "", 8.5)
            for c in cols:
                f = cells.get((r, c))
                mark = _mark(f) if f else ""
                if mark:
                    self.set_fill_color(*(REVIEW_SOFT if mark == "review" else EDITED_SOFT))
                self.set_text_color(*(REVIEW if mark == "review" else EDITED if mark == "edited" else INK))
                text = value_text(f) if f and f.get("status") not in EMPTY else ""
                self.cell(cw, 7, text, border=1, fill=bool(mark), align="C")
            self.ln()
        self.ln(3)

    def empty_line(self, labels: list[str]):
        if not labels:
            return
        self.set_font("Noto", "", 8)
        self.set_text_color(*MUTED)
        self.multi_cell(0, 4.5, "Non renseignés : " + ", ".join(labels))
        self.ln(2)


def _section_blocks(fields: list[dict]):
    """Champs d'une section -> blocs « lignes » et « tableaux » dans l'ordre de la page."""
    tables: dict[str, list[dict]] = {}
    for f in fields:
        if " | " in f.get("label", ""):
            tables.setdefault(f["label"].split(" | ", 1)[0], []).append(f)
    # Un vrai tableau : plusieurs rangées qui partagent les mêmes colonnes
    col_sets = Counter(tuple(sorted(x["label"].split(" | ", 1)[1] for x in fs)) for fs in tables.values())
    shared = {cols for cols, n in col_sets.items() if n >= 2 and len(cols) >= 2}
    grid_rows = {r for r, fs in tables.items() if tuple(sorted(x["label"].split(" | ", 1)[1] for x in fs)) in shared}
    blocks, current_grid, plain = [], None, []
    for f in fields:
        row = f["label"].split(" | ", 1)[0] if " | " in f.get("label", "") else None
        if row in grid_rows:
            if plain:
                blocks.append(("rows", plain))
                plain = []
            if current_grid is None:
                current_grid = {"rows": [], "cols": [], "cells": {}}
                blocks.append(("grid", current_grid))
            col = f["label"].split(" | ", 1)[1]
            if row not in current_grid["rows"]:
                current_grid["rows"].append(row)
            if col not in current_grid["cols"]:
                current_grid["cols"].append(col)
            current_grid["cells"][(row, col)] = f
        else:
            current_grid = None
            plain.append(f)
    if plain:
        blocks.append(("rows", plain))
    return blocks


def build_pdf(final: dict) -> bytes:
    """Résultat final (store.final_json) -> octets du PDF."""
    pages = final.get("pages", [])
    counts = Counter()
    for p in pages:
        for f in p.get("fields", []):
            counts["review" if f.get("status") in TO_REVIEW else "empty" if f.get("status") in EMPTY else
                   "edited" if f.get("origin") in ("CORRECTED", "MANUAL") else "known"] += 1
    pdf = RecordPDF(final)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.title_block(counts)
    for i, page in enumerate(pages):
        pdf.page_heading(page, i, len(pages))
        sections: dict[str, list[dict]] = {}
        for f in page.get("fields", []):
            sections.setdefault(f.get("section") or "Champs lus", []).append(f)
        for name, fields in sections.items():
            filled = [f for f in fields if f.get("status") not in EMPTY]
            if not filled:
                continue
            pdf.section_heading(name)
            for kind, block in _section_blocks(fields):
                if kind == "grid":
                    pdf.grid(block["rows"], block["cols"], block["cells"])
                else:
                    pdf.field_rows([f for f in block if f.get("status") not in EMPTY])
            pdf.empty_line([f["label"] for f in fields if f.get("status") in EMPTY and " | " not in f.get("label", "")])
    return bytes(pdf.output())
