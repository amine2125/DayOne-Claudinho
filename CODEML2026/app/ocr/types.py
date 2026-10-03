"""Structures OCR internes, indépendantes du moteur (PaddleOCR, fake, etc.)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Script = Literal["latin", "arabic", "unknown"]


@dataclass(frozen=True)
class BBox:
    """Boîte alignée sur les axes, en pixels de l'image de référence."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    def v_overlap(self, other: BBox) -> float:
        """Recouvrement vertical relatif (0..1) par rapport à la plus petite hauteur."""
        inter = min(self.y2, other.y2) - max(self.y1, other.y1)
        return max(0.0, inter) / max(1.0, min(self.h, other.h))

    def h_overlap(self, other: BBox) -> float:
        inter = min(self.x2, other.x2) - max(self.x1, other.x1)
        return max(0.0, inter) / max(1.0, min(self.w, other.w))

    def iou(self, other: BBox) -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        inter = ix * iy
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0 else 0.0

    def union(self, other: BBox) -> BBox:
        return BBox(min(self.x1, other.x1), min(self.y1, other.y1),
                    max(self.x2, other.x2), max(self.y2, other.y2))

    def to_list(self) -> list[int]:
        return [round(self.x1), round(self.y1), round(self.x2), round(self.y2)]

    @staticmethod
    def from_polygon(points: list[list[float]] | list[tuple[float, float]]) -> BBox:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return BBox(min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class OCRToken:
    """Une ligne/un mot reconnu par l'OCR, avec sa confiance brute."""

    text: str
    confidence: float
    bbox: BBox
    script: Script = "unknown"
    engine: str = "paddleocr"


@dataclass
class OCRPage:
    tokens: list[OCRToken]
    width: int
    height: int
    engine_info: dict = field(default_factory=dict)


def detect_script(text: str) -> Script:
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha() or "À" <= ch <= "ſ")
    if arabic == 0 and latin == 0:
        return "unknown"
    return "arabic" if arabic >= latin else "latin"
