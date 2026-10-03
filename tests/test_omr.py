import cv2
import numpy as np
import pytest

from app.ocr.types import BBox
from app.vision.omr import (
    CheckboxResult,
    detect_checkboxes,
    find_adjacent_checkbox,
    inspect_checkbox,
    resolve_group_selection,
)


def test_inspect_empty_and_checked_checkbox():
    # Créer une image synthétique avec une case vide et une case cochée
    img = np.full((100, 200), 255, dtype=np.uint8)

    # Case 1 (vide) : carré noir de 20x20 à x=20, y=20
    cv2.rectangle(img, (20, 20), (40, 40), 0, 2)

    # Case 2 (cochée) : carré noir de 20x20 à x=80, y=20 avec une croix dedans
    cv2.rectangle(img, (80, 20), (100, 40), 0, 2)
    cv2.line(img, (83, 23), (97, 37), 0, 2)
    cv2.line(img, (83, 37), (97, 23), 0, 2)

    res_empty = inspect_checkbox(img, BBox(20, 20, 40, 40))
    assert not res_empty.checked
    assert res_empty.state == "EMPTY"

    res_checked = inspect_checkbox(img, BBox(80, 20, 100, 40))
    assert res_checked.checked
    assert res_checked.state == "CHECKED"


def test_detect_checkboxes():
    img = np.full((120, 240), 255, dtype=np.uint8)
    cv2.rectangle(img, (30, 30), (52, 52), 0, 2)
    cv2.rectangle(img, (100, 30), (122, 52), 0, 2)

    boxes = detect_checkboxes(img)
    assert len(boxes) >= 2


def test_resolve_group_selection():
    img = np.full((100, 300), 255, dtype=np.uint8)

    # Option A (non cochée): case à x=20, libellé à x=45
    cv2.rectangle(img, (20, 30), (40, 50), 0, 2)

    # Option B (cochée): case à x=120, libellé à x=145
    cv2.rectangle(img, (120, 30), (140, 50), 0, 2)
    cv2.line(img, (123, 33), (137, 47), 0, 2)
    cv2.line(img, (123, 47), (137, 33), 0, 2)

    options = {
        "A": BBox(45, 30, 65, 50),
        "B": BBox(145, 30, 165, 50),
    }

    choice, conf, status = resolve_group_selection(img, options)
    assert choice == "B"
    assert status == "CONNU"
