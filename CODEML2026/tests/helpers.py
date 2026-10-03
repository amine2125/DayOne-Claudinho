from app.ocr.types import BBox, OCRPage, OCRToken, detect_script


def tok(text: str, x1: float, y1: float, x2: float, y2: float, conf: float = 0.95) -> OCRToken:
    return OCRToken(text, conf, BBox(x1, y1, x2, y2), detect_script(text), "test")


def page(tokens: list[OCRToken], w: int = 1600, h: int = 1200) -> OCRPage:
    return OCRPage(tokens, w, h)
