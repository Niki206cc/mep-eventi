"""Flusso principale: fonti -> pagina -> locandina -> IA -> anti-duplicati -> The Events Calendar."""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .extract import parse_page
from .http import Http
from .images import load_image, pick_best, render_pdf, slugify
from .llm import LLM
from .models import RawEvent
from .notify import esc, telegram
from .sources import build_source
from .state import LIVE
from .store import FINAL, Store
from .wordpress import SiteDownError, WordPress, norm, similar

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------- pianificazione date
@dataclass
class Slot:
    start_day: date
    end_day: date
    start_time: str | None
    end_time: str | None

    @property
    def all_day(self) -> bool:
        return not self.start_time

    def wp_dates(self) -> tuple[str, str]:
        if self.all_day:
            return f"{self.start_day} 00:00:00", f"{self.end_day} 23:59:59"
        st = datetime.combine(self.start_day, _t(self.start_time))
        if self.end_time:
            en = datetime.combine(self.end_day, _t(self.end_time))
            if en <= st:  # finisce dopo mezzanotte
                en += timedelta(days=1)
        else:
            en = st + timedelta(hours=2)
            if self.end_day > self.start_day:
                en = datetime.combine(self.end_day, en.time())
        return st.strftime("%Y-%m-%d %H:%M:%S"), en.strftime("%Y-%m-%d %H:%M:%S")


def _t(hhmm: str):
    h, m = (hhmm.strip().replace(".", ":") + ":00").split(":")[:2]
    return datetime.strptime(f"{int(h) % 24:02d}:{int(m):02d}", "%H:%M").time()


def _valid_time(v) -> str | None:
    if not v or not isinstance(v, str):
        return None
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", v)
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)) % 24:02d}:{m.group(2)}"


def _valid_date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def plan_slots(data: dict, today: date, st: Settings) -> tuple[str, list[Slot]]:
    """Ritorna (stato, slot). stato 'ok' oppure il motivo dello scarto."""
    kind = (data.get("kind") or "singolo").lower()
    occ = []
    for o in data.get("occurrences") or []:
        d = _valid_date(o.get("date")) if isinstance(o, dict) else None
        if d:
            occ.append((d, _valid_time(o.get("start_time")), _valid_time(o.get("end_time"))))
    occ.sort(key=lambda x: x[0])
    if not occ:
        return "no_dates", []
    horizon = today + timedelta(days=st.horizon_days)

    if kind == "ricorrente" and st.skip_recurring:
        return "recurring_skipped", []

    if kind in ("periodo", "ricorrente"):
        start = occ[0][0]
        end = _valid_date(data.get("period_end")) or occ[-1][0]
        if end < start:
            end = start
        if end < today:
            return "past", []
        if start > horizon:
            return "out_of_horizon", []
        if (end - start).days > st.max_period_days:
            return "too_long", []
        return "ok", [Slot(start, end, occ[0][1], occ[0][2])]

    future = [o for o in occ if today <= o[0] <= horizon]
    if not future:
        return ("past" if occ[-1][0] < today else "out_of_horizon"), []
    return "ok", [Slot(d, d, s, e) for d, s, e in future[: st.max_occurrences]]


# ---------------------------------------------------------------------- report
class LLMBudgetReached(Exception):
    """Raggiunto il numero massimo di analisi IA per questo giro."""


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)

    def text(self, st: Settings) -> str:
        lines = [f"<b>Montagne &amp; Paesi – import eventi</b> ({datetime.now(ZoneInfo(st.timezone)):%d/%m %H:%M})"]
        stato = {"draft": "in bozza", "pending": "in revisione", "publish": "pubblicati"}.get(st.publish_status, st.publish_status)
        lines.append(f"Nuovi eventi: <b>{len(self.created)}</b> ({stato})")
        lines += self.created[:40]
        if self.updated:
            lines.append(f"Aggiornati: {len(self.updated)}")
            lines += self.updated[:20]
        if self.skipped:
            labels = {"not_event": "non eventi", "past": "passati", "duplicate": "duplicati",
                      "recurring_skipped": "ricorrenti", "out_of_horizon": "troppo lontani",
                      "no_dates": "senza date", "too_long": "periodo troppo lungo"}
            lines.append("Scartati: " + ", ".join(f"{labels.get(k, k)} {v}" for k, v in self.skipped.items()))
        if self.errors:
            lines.append(f"<b>Errori: {len(self.errors)}</b>")
            lines += [f"• {esc(e)}" for e in self.errors[:15]]
        lines += self.notes
        return "\n".join(lines)


def sanitize_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|iframe|object|embed)[^>]*>.*?</\1>", "", h or "")
    h = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h)
    h = re.sub(r"(?i)javascript:", "", h)
    return h.strip()


# ---------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(self, st: Settings, dry_run: bool = False):
        self.st = st
        self.dry = dry_run
        self.tz = ZoneInfo(st.timezone)
        self.http = Http(st.user_agent, st.request_delay)
        self.store = Store(st.data_dir)
        self.llm = LLM(st)
        self.wp = None if dry_run else WordPress(st, self.store)
        self.report = Report()

    def run(self, only_source: str | None = None, limit: int | None = None, trigger: str = "pianificato") -> Report:
        today = datetime.now(self.tz).date()
        run_id = None if self.dry else self.store.start_run(trigger + (f" ({only_source})" if only_source else ""))
        per_source: dict[str, dict] = {}
        status = "ok"
        LIVE.update(running=True, trigger=trigger, started_at=datetime.now(), source="", done=0, total=0, current="")
        try:
            if self.wp:
                self.wp.check()
            sources = [s for s in self.st.load_sources() if not only_source or s["id"] == only_source]
            new_count = 0
            stop = False
            for cfg in sources:
                if stop:
                    break
                stats = per_source.setdefault(cfg["id"], {"trovati": 0, "nuovi": 0, "errori": 0})
                LIVE.update(source=cfg.get("name", cfg["id"]), done=0, total=0, current="lettura fonte…")
                try:
                    raws = build_source(cfg, self.http, today).fetch()
                except Exception as e:  # noqa: BLE001
                    log.exception("fonte %s non disponibile", cfg.get("id"))
                    self.report.errors.append(f"{cfg.get('name', cfg.get('id'))}: fonte non raggiungibile ({e})"[:300])
                    stats["errori"] += 1
                    stats["fonte_ko"] = str(e)[:200]
                    continue
                todo = raws[:limit] if limit else raws
                stats["trovati"] = len(raws)
                LIVE.update(total=len(todo))
                for n, raw in enumerate(todo, 1):
                    if new_count >= self.st.max_new_per_run:
                        self.report.notes.append(f"Raggiunto il limite di {self.st.max_new_per_run} nuovi eventi: il resto al prossimo giro.")
                        stop = True
                        break
                    LIVE.update(done=n, current=raw.title or raw.url)
                    try:
                        if self.process(raw, today):
                            new_count += 1
                            stats["nuovi"] += 1
                            if self.st.event_pause and not self.dry:
                                LIVE.update(current=f"pausa {self.st.event_pause}s (protezione sito)")
                                time.sleep(self.st.event_pause)
                    except (SiteDownError, LLMBudgetReached):
                        raise
                    except Exception as e:  # noqa: BLE001
                        log.exception("errore su %s", raw.url)
                        stats["errori"] += 1
                        self._fail(raw, e)
        except LLMBudgetReached:
            self.report.notes.append(f"Raggiunto il limite di {self.st.llm_max_calls} analisi IA per giro: il resto al prossimo.")
        except SiteDownError as e:
            status = "interrotto"
            log.error("%s", e)
            self.report.errors.append(f"Giro interrotto: {e}"[:400])
        except Exception as e:  # noqa: BLE001
            status = "fallito"
            self.report.errors.append(f"Giro interrotto: {e}"[:400])
            raise
        finally:
            if self.report.errors and status == "ok":
                status = "con errori"
            if not self.dry:
                telegram(self.st, self.report.text(self.st))
                self.store.finish_run(run_id, status, len(self.report.created), len(self.report.updated),
                                      sum(self.report.skipped.values()), len(self.report.errors), per_source,
                                      self.report.text(self.st))
            LIVE.update(running=False, current="", source="")
            log.info("Fine: %d nuovi, %d aggiornati, scartati %s, errori %d",
                     len(self.report.created), len(self.report.updated), dict(self.report.skipped), len(self.report.errors))
            cost = self.llm.tokens_in / 1e6 * self.st.price_in + self.llm.tokens_out / 1e6 * self.st.price_out
            log.info("IA: %d analisi, %d token in, %d token out, circa %.3f $", self.llm.calls,
                     self.llm.tokens_in, self.llm.tokens_out, cost)
            self.report.notes.append(f"IA: {self.llm.calls} analisi, circa {cost:.2f} $")
        return self.report

    # ------------------------------------------------------------------
    def _fail(self, raw: RawEvent, e: Exception):
        row = self.store.get(raw.source_id, raw.uid)
        attempts = (row["attempts"] if row else 0) + 1
        if not self.dry:
            self.store.save(raw.source_id, raw.uid, url=raw.url, title=raw.title, status="error",
                            attempts=attempts, note=str(e)[:500], content_hash=raw.content_hash(),
                            source_name=raw.source_name)
        self.report.errors.append(f"{raw.title or raw.url}: {e}"[:300])

    def _skip(self, raw: RawEvent, status: str, note: str = "") -> bool:
        self.report.skipped[status] += 1
        log.info("[%s] scartato (%s) %s %s", raw.source_id, status, raw.title[:60], note)
        if not self.dry:
            self.store.save(raw.source_id, raw.uid, url=raw.url, title=raw.title or raw.url, status=status,
                            content_hash=raw.content_hash(), note=note[:500], attempts=0, source_name=raw.source_name,
                            event_date=raw.hints.get("start_date"), city=raw.hints.get("comune"))
        return False

    def process(self, raw: RawEvent, today: date) -> bool:
        row = self.store.get(raw.source_id, raw.uid)

        if raw.needs_page_fetch:
            html = self.http.get_text(raw.url)
            enrich_from_page(raw, html)

        h = raw.content_hash()
        if row and row["content_hash"] == h:
            if row["status"] in FINAL or (row["status"] == "error" and row["attempts"] >= MAX_ATTEMPTS):
                return False

        # Risparmio crediti: schede già valutate che cambiano solo per dettagli (menu, "eventi correlati",
        # contatori...) non vengono rianalizzate dall'IA.
        if row and row["content_hash"] != h and row["status"] in FINAL:
            st_old = row["status"]
            if st_old in ("created", "updated"):
                if not self.st.update_changed:
                    # non sovrascrive le modifiche fatte a mano sul sito
                    if not self.dry:
                        self.store.save(raw.source_id, raw.uid, content_hash=h, note="modificato alla fonte (non riletto)")
                    return False
            elif st_old == "out_of_horizon":
                seen = _valid_date(row["last_seen"])
                if seen and (today - seen).days < self.st.recheck_days:
                    return False
            elif (raw.title or "").strip() == (row["title"] or "").strip():
                if not self.dry:
                    self.store.save(raw.source_id, raw.uid, content_hash=h)
                return False

        end_hint = _valid_date(raw.hints.get("end_date"))
        if end_hint and end_hint < today:
            return self._skip(raw, "past")
        start_hint = _valid_date(raw.hints.get("start_date"))
        if start_hint and start_hint > today + timedelta(days=self.st.horizon_days):
            return self._skip(raw, "out_of_horizon")

        if self.llm.calls >= self.st.llm_max_calls:
            raise LLMBudgetReached()

        # locandina: immagini candidate + eventuale PDF
        pictures = [p for p in (load_image(self.http, u) for u in raw.image_urls[:6]) if p]
        best = pick_best(pictures, self.st.min_image_side)
        pdf_text = ""
        for pdf in raw.pdf_urls[:1]:
            pic, pdf_text = render_pdf(self.http, pdf)  # il testo del PDF serve comunque all'IA
            if pic and best is None:  # la pagina del PDF come locandina solo se manca un'immagine valida
                best = pick_best([pic], self.st.min_image_side)

        data = self.llm.analyze(raw, today, best, pdf_text)
        if not data.get("is_event"):
            return self._skip(raw, "not_event", data.get("not_event_reason") or "")

        status, slots = plan_slots(data, today, self.st)
        if status != "ok":
            return self._skip(raw, status)

        title = (data.get("title") or raw.title).strip()[:150]
        venue = data.get("venue") or {}
        city = venue.get("city") or raw.hints.get("comune") or ""

        if self.dry:
            print(json.dumps({"fonte": raw.source_id, "url": raw.url, "immagine": best.source_url if best else None,
                              "slots": [s.wp_dates() for s in slots], "ia": data}, ensure_ascii=False, indent=2))
            self.report.created.append(title)
            return True

        # già importato ma cambiato alla fonte -> aggiorna
        old_ids = self.store.wp_ids(row) if row else []
        if row and row["status"] in ("created", "updated") and old_ids:
            if len(old_ids) == 1 and len(slots) == 1:
                payload = self._payload(raw, data, slots[0], row["media_id"])
                self.wp.update_event(old_ids[0], payload)
                self.store.save(raw.source_id, raw.uid, status="updated", content_hash=h, title=title, attempts=0)
                self.report.updated.append(f"• <a href=\"{self.wp.edit_link(old_ids[0])}\">{esc(title)}</a>")
            else:
                self.store.save(raw.source_id, raw.uid, content_hash=h, note="modificato alla fonte: da controllare")
                self.report.notes.append(f"Da controllare (cambiato alla fonte): {esc(title)} – {raw.url}")
            return False

        # anti-duplicati: stesso giorno, titolo simile (altre fonti o già sul sito)
        todo = []
        for s in slots:
            day = s.start_day.isoformat()
            dup = None
            for fp in self.store.fingerprints_on(day):
                if (fp["source_id"], fp["uid"]) == (raw.source_id, raw.uid):
                    continue
                if similar(fp["title"], title) > 0.82 and (not city or not fp["city"] or norm(fp["city"]) == norm(city)):
                    dup = fp["wp_id"]
                    break
            if dup is None and self.st.check_existing_on_site:
                dup = self.wp.find_existing(title, day)
            if dup is None:
                todo.append(s)
        if not todo:
            return self._skip(raw, "duplicate")

        media_id = row["media_id"] if row and row["media_id"] else None
        if best and not media_id:
            slug = slugify(title)
            media_id = self.wp.upload_media(best.data, best.filename(slug), best.mime, title=title,
                                            alt=f"Locandina: {title}", caption=f"Fonte: {raw.source_name}")
            # salvato subito: se la creazione dell'evento fallisce, al giro dopo si riusa la stessa immagine
            self.store.save(raw.source_id, raw.uid, url=raw.url, title=title, media_id=media_id,
                            source_name=raw.source_name)

        created = []
        for s in todo:
            payload = self._payload(raw, data, s, media_id)
            ev = self.wp.create_event(payload)
            created.append(ev["id"])
            self.store.add_fingerprint(s.start_day.isoformat(), city, title, ev["id"], raw.source_id, raw.uid)

        self.store.save(raw.source_id, raw.uid, url=raw.url, title=title, status="created", wp_ids=created,
                        media_id=media_id, content_hash=h, attempts=0, note="", source_name=raw.source_name,
                        event_date=todo[0].start_day.isoformat(), city=city,
                        image_url=best.source_url if best else None)
        first = todo[0].start_day.strftime("%d/%m")
        extra = f" (+{len(created) - 1} date)" if len(created) > 1 else ""
        self.report.created.append(
            f"• <a href=\"{self.wp.edit_link(created[0])}\">{esc(title)}</a> – {first}{extra}, {esc(city)} <i>[{esc(raw.source_id)}]</i>")
        log.info("[%s] creato %s -> %s", raw.source_id, title, created)
        return True

    # ------------------------------------------------------------------
    def _payload(self, raw: RawEvent, data: dict, slot: Slot, media_id: int | None) -> dict:
        start, end = slot.wp_dates()
        desc = sanitize_html(data.get("description_html") or "")
        if self.st.add_source_link:
            desc += (f'\n<p class="mep-fonte"><em>Fonte: <a href="{raw.url}" target="_blank" '
                     f'rel="noopener nofollow">{esc(raw.source_name)}</a></em></p>')
        payload = {
            "title": (data.get("title") or raw.title).strip()[:150],
            "description": desc,
            "excerpt": (data.get("excerpt") or "")[:300],
            "start_date": start,
            "end_date": end,
            "all_day": slot.all_day,
            "timezone": self.st.timezone,
            "status": self.st.publish_status,
            "website": raw.url,
        }
        if data.get("cost"):
            payload["cost"] = str(data["cost"])[:100]
        if media_id:
            payload["image"] = str(media_id)  # TEC vuole una stringa (ID o URL)

        venue = dict(data.get("venue") or {})
        if not venue.get("city"):
            venue["city"] = (raw.hints.get("comune") or "").split(",")[0].strip() or None
        if not venue.get("province"):
            venue["province"] = raw.hints.get("provincia")
        vid = self.wp.venue_id(venue)
        if vid:
            payload["venue"] = vid
        oid = self.wp.organizer_id(data.get("organizer"))
        if oid:
            payload["organizer"] = [oid]

        cat = data.get("category")
        if cat not in self.st.categories:
            cat = "Altro" if "Altro" in self.st.categories else None
        cid = self.wp.category_id(cat) if cat else None
        if cid:
            payload["categories"] = [cid]

        tags = []
        if self.st.tag_comune and (venue.get("city") or raw.hints.get("comune")):
            tags.append((venue.get("city") or raw.hints.get("comune")).split(",")[0].strip())
        if self.st.tag_zona and raw.hints.get("zona"):
            tags.append(raw.hints["zona"])
        tag_ids = list(dict.fromkeys(t for t in (self.wp.tag_id(x) for x in dict.fromkeys(tags)) if t))
        if tag_ids:
            payload["tags"] = tag_ids
        return payload


def enrich_from_page(raw: RawEvent, html: str) -> None:
    page = parse_page(html, raw.url)
    raw.title = raw.title or page["title"]
    if page["text"]:
        raw.text = (raw.text + "\n\n--- Pagina web ---\n" + page["text"]).strip() if raw.text else page["text"]
    for u in page["images"]:
        if u not in raw.image_urls:
            raw.image_urls.append(u)
    for u in page["pdfs"]:
        if u not in raw.pdf_urls:
            raw.pdf_urls.append(u)
