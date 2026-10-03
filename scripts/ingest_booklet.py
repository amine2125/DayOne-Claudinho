"""Script CLI d'ingestion complète d'un carnet de santé maternel ou d'un lot de registres.

Permet de traiter un lot complet de pages (Pages 1 à 8 par patiente) :
  - Détection automatique des pages
  - Consolidation longitudinale complète (Profil, Visites prénatales, Accouchement, Postpartum)
  - Détection des alertes cliniques de sécurité
  - Export standard JSON et FHIR R4
  - Chiffrement au repos sans aucune fuite PII

Usage :
  python scripts/ingest_booklet.py --images-dir "data/Paper Registry" --patient-index 1
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ajouter la racine du projet au sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ocr.engine import get_engine
from app.patient_linking.linker import PatientLinker
from app.sessions.booklet_session import BookletSessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ingest_booklet")


def run_booklet_ingestion(images_dir: Path, patient_index: int = 1, output_dir: Path | None = None) -> dict:
    start_page = (patient_index - 1) * 8 + 1
    end_page = start_page + 7

    log.info(f"=== Ingestion du Carnet de Santé pour la Patiente #{patient_index} (Pages {start_page:02d} à {end_page:02d}) ===")

    session_mgr = BookletSessionManager()
    session = session_mgr.start_session(f"SF-CLI-{patient_index}")

    page_files = []
    for p_num in range(start_page, end_page + 1):
        candidates = list(images_dir.glob(f"dossiers_specimen_10_patientes-{p_num:02d}*.png"))
        if candidates:
            page_files.append((p_num - start_page + 1, candidates[0]))

    if not page_files:
        log.warning(f"Aucune image trouvée pour la patiente #{patient_index} dans {images_dir}")
        return {}

    log.info(f"{len(page_files)} pages trouvées à numériser.")

    for booklet_page_num, img_path in page_files:
        log.info(f"-> Traitement de la page {booklet_page_num} : {img_path.name}")
        img_bytes = img_path.read_bytes()
        res = session_mgr.process_page_scan(
            session_id=session.session_id,
            image_bytes=img_bytes,
            page_number=booklet_page_num,
        )
        log.info(f"   Page {booklet_page_num} traitée ({res['extracted_count']} enregistrements extraits, diff={res['is_rescan']})")

    # Clôture et consolidation finale
    final_res = session_mgr.finalize_booklet(session.session_id)
    log.info(f"✅ Carnet #{patient_index} finalisé avec succès !")
    log.info(f"   ID Patiente anonyme : {final_res['patient_id']}")
    log.info(f"   Visites enregistrées : {final_res['total_visits_linked']}")
    log.info(f"   Alertes cliniques détectées : {len(final_res['clinical_alerts'])}")

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_dir / f"dossier_patiente_{final_res['patient_id']}.json"
        out_file.write_text(json.dumps(final_res, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"   Export JSON généré : {out_file}")

    return final_res


def main():
    parser = argparse.ArgumentParser(description="Ingestion CLI d'un carnet de santé maternel complet")
    parser.add_argument("--images-dir", type=str, default="data/Paper Registry", help="Dossier contenant les scans")
    parser.add_argument("--patient-index", type=int, default=1, help="Numéro de la patiente (1 à 10)")
    parser.add_argument("--output-dir", type=str, default="data/exports", help="Dossier d'export des résultats")
    args = parser.parse_args()

    # Charger le moteur OCR local
    get_engine()

    img_dir = Path(args.images_dir)
    out_dir = Path(args.output_dir)
    run_booklet_ingestion(img_dir, args.patient_index, out_dir)


if __name__ == "__main__":
    main()
