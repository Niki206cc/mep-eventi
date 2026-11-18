"""Estrazione di testo, immagini, PDF e dati strutturati da una pagina HTML."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

MAX_TEXT = 12000

_NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg", "button"]
_NOISE_CLASS = re.compile(
    r"(cookie|iubenda|share|social|breadcrumb|menu|navbar|sidebar|newsletter|related|correlat|footer|header|banner-cookie|modal)",
    re.I,
)
_MAIN_SELECTORS = [
    "article", "main", "[role=main]", ".entry-content", ".post-content", ".single-content",
    "#content", ".content", "#main",
]
_IMG_SKIP = re.compile(r"(logo|icon|icona|favicon|sprite|placeholder|avatar|stemma|banner-app|pixel|spacer|loader)", re.I)
_CAL_LINK = re.compile(r"(calendar\.google|outlook\.live|\.ics(\?|$)|addtocalendar|action=TEMPLATE)", re.I)


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_jsonld_events(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if "@graph" in item and isinstance(item["@graph"], list):
                    stack.extend(item["@graph"])
                t = item.get("@type")
                types = t if isinstance(t, list) else [t]
                if any(isinstance(x, str) and x.endswith("Event") for x in types):
                    out.append(item)
    return out


def meta_content(soup: BeautifulSoup, *names: str) -> str:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _main_node(soup: BeautifulSoup):
    for sel in _MAIN_SELECTORS:
        node = soup.select_one(sel)
        if node and len(node.get_text(" ", strip=True)) > 200:
            return node
    return soup.body or soup


def clean_text(node) -> str:
    text = node.get_text("\n", strip=True)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out, prev = [], None
    for ln in lines:
        if ln and ln != prev:
            out.append(ln)
        prev = ln
    return "\n".join(out)


def html_to_text(html: str) -> str:
    return clean_text(soup_of(html))


def parse_page(html: str, base_url: str) -> dict:
    """Ritorna {title, text, images, pdfs, jsonld, calendar_links}."""
    soup = soup_of(html)
    jsonld = extract_jsonld_events(soup)

    title = meta_content(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)

    images: list[str] = []
    og = meta_content(soup, "og:image", "og:image:url", "twitter:image")
    if og:
        images.append(urljoin(base_url, og))

    calendar_links = []
    for a in soup.find_all("a", href=True):
        if _CAL_LINK.search(a["href"]):
            calendar_links.append(a["href"])

    pdfs = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if urlparse(href).path.lower().endswith(".pdf") and href not in pdfs:
            pdfs.append(href)

    for t in soup(_NOISE_TAGS):
        t.decompose()
    for t in soup.find_all(attrs={"class": _NOISE_CLASS}):
        if t.name not in ("body", "html", "main", "article"):
            t.decompose()

    main = _main_node(soup)

    for img in main.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        srcset = img.get("data-srcset") or img.get("srcset")
        if srcset:  # prendi la variante più grande
            try:
                best = max(
                    (p.strip().split(" ") for p in srcset.split(",") if p.strip()),
                    key=lambda p: int(re.sub(r"\D", "", p[1]) or 0) if len(p) > 1 else 0,
                )
                src = best[0]
            except (ValueError, IndexError):
                pass
        if not src or src.startswith("data:") or _IMG_SKIP.search(src + " " + (img.get("alt") or "")):
            continue
        full = urljoin(base_url, src)
        if full not in images:
            images.append(full)
    # immagini linkate direttamente (lightbox / allegati)
    for a in main.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if re.search(r"\.(jpe?g|png|webp)(\?|$)", href, re.I) and href not in images and not _IMG_SKIP.search(href):
            images.append(href)

    text = clean_text(main)
    if calendar_links:
        text += "\n\nLink 'aggiungi al calendario' presenti nella pagina (contengono date ISO):\n" + "\n".join(calendar_links[:4])
    if jsonld:
        text = "Dati strutturati JSON-LD:\n" + json.dumps(jsonld[:2], ensure_ascii=False)[:3000] + "\n\n" + text

    return {"title": title, "text": text[:MAX_TEXT], "images": images[:12], "pdfs": pdfs[:5], "jsonld": jsonld}


def find_links(html: str, base_url: str, pattern: str, exclude: str | None = None) -> list[str]:
    soup = soup_of(html)
    rx = re.compile(pattern)
    ex = re.compile(exclude) if exclude else None
    out: list[str] = []
    base_host = urlparse(base_url).netloc
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(href).netloc != base_host:
            continue
        if rx.search(href) and not (ex and ex.search(href)) and href not in out:
            out.append(href)
    return out
