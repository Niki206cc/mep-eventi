"""Download e scelta della locandina; conversione del PDF in immagine."""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from PIL import Image

from .http import Http

log = logging.getLogger(__name__)

MAX_SIDE = 1600
MAX_BYTES = 15 * 1024 * 1024


@dataclass
class Picture:
    data: bytes          # JPEG/PNG pronto per l'upload
    mime: str
    width: int
    height: int
    source_url: str
    from_pdf: bool = False

    @property
    def portrait(self) -> bool:
        return self.height > self.width * 1.15

    def filename(self, slug: str) -> str:
        ext = "png" if self.mime == "image/png" else "jpg"
        return f"{slug[:70] or 'evento'}-locandina.{ext}"


def _normalize(img: Image.Image, source_url: str, from_pdf=False) -> Picture:
    if img.mode in ("P", "LA", "RGBA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE * 2))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True, progressive=True)
    return Picture(buf.getvalue(), "image/jpeg", img.width, img.height, source_url, from_pdf)


def load_image(http: Http, url: str) -> Picture | None:
    try:
        r = http.get(url, timeout=40)
    except Exception as e:  # noqa: BLE001
        log.debug("immagine non scaricabile %s: %s", url, e)
        return None
    if len(r.content) > MAX_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except Exception:  # noqa: BLE001
        return None
    return _normalize(img, url)


def render_pdf(http: Http, url: str) -> tuple[Picture | None, str]:
    """Prima pagina del PDF come immagine + testo del PDF (per l'IA)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF non installato: salto il PDF %s", url)
        return None, ""
    try:
        r = http.get(url, timeout=60)
        if len(r.content) > 30 * 1024 * 1024:
            return None, ""
        doc = fitz.open(stream=r.content, filetype="pdf")
        text = "\n".join(doc[i].get_text() for i in range(min(3, doc.page_count)))
        pix = doc[0].get_pixmap(dpi=130)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return _normalize(img, url, from_pdf=True), text[:4000]
    except Exception as e:  # noqa: BLE001
        log.warning("PDF non leggibile %s: %s", url, e)
        return None, ""


def pick_best(pictures: list[Picture], min_side: int) -> Picture | None:
    """Sceglie la locandina: scarta le immagini piccole, preferisce il formato verticale e la più grande."""
    seen = set()
    good = []
    for i, p in enumerate(pictures):
        h = hashlib.md5(p.data).hexdigest()
        if h in seen or min(p.width, p.height) < min_side:
            continue
        seen.add(h)
        score = p.width * p.height
        if p.portrait:
            score *= 1.6           # le locandine sono quasi sempre verticali
        if i == 0:
            score *= 1.25          # la prima candidata è l'immagine principale della fonte
        if p.from_pdf:
            score *= 0.9
        good.append((score, p))
    if not good:
        return None
    return max(good, key=lambda x: x[0])[1]


def slugify(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def host_of(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "")


def shrink_for_llm(pic: Picture, side: int) -> Picture:
    """Copia ridotta della locandina da mandare all'IA: meno pixel = meno token.
    La locandina caricata sul sito resta a piena risoluzione."""
    if not side or max(pic.width, pic.height) <= side:
        return pic
    try:
        img = Image.open(io.BytesIO(pic.data)).convert("RGB")
        img.thumbnail((side, side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80, optimize=True)
        return Picture(buf.getvalue(), "image/jpeg", img.width, img.height, pic.source_url, pic.from_pdf)
    except Exception:  # noqa: BLE001
        return pic
