import io
import json
from datetime import date

import pytest
from PIL import Image

from app.config import Settings
from app.extract import find_links, parse_page
from app.images import Picture, pick_best
from app.llm import parse_json
from app.pipeline import Pipeline, Slot, plan_slots
from app.sources.municipium import MunicipiumSource
from app.sources.wp_valseriana import ValserianaSource

TODAY = date(2026, 11, 18)


def png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


class FakeResp:
    def __init__(self, content=b"", text="", js=None):
        self.content, self.text, self._js = content, text, js
        self.encoding = "utf-8"

    def json(self):
        return self._js


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes

    def _find(self, url):
        for k, v in self.routes.items():
            if k in url:
                return v
        raise RuntimeError(f"404 {url}")

    def get(self, url, **kw):
        v = self._find(url)
        return v if isinstance(v, FakeResp) else FakeResp(content=v if isinstance(v, bytes) else b"")

    def get_json(self, url, **kw):
        return self._find(url)

    def get_text(self, url, **kw):
        return self._find(url)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return Settings()


# ---------------------------------------------------------------- date
def test_plan_singolo_and_past(st):
    ok, slots = plan_slots({"kind": "singolo", "occurrences": [{"date": "2026-12-12", "start_time": "20:45"}]}, TODAY, st)
    assert ok == "ok" and slots[0].wp_dates() == ("2026-12-12 20:45:00", "2026-12-12 22:45:00")
    assert plan_slots({"kind": "singolo", "occurrences": [{"date": "2026-10-01"}]}, TODAY, st)[0] == "past"


def test_plan_piu_date_filters_past_and_caps(st):
    occ = [{"date": f"2026-11-{d:02d}", "start_time": "21:00", "end_time": "23:00"} for d in range(10, 30)]
    ok, slots = plan_slots({"kind": "piu_date", "occurrences": occ}, TODAY, st)
    assert ok == "ok" and len(slots) == st.max_occurrences and slots[0].start_day == date(2026, 11, 18)


def test_plan_periodo_and_recurring(st):
    ok, slots = plan_slots({"kind": "periodo", "occurrences": [{"date": "2026-12-07"}], "period_end": "2027-01-06"}, TODAY, st)
    assert ok == "ok" and slots[0].all_day and slots[0].wp_dates() == ("2026-12-07 00:00:00", "2027-01-06 23:59:59")
    assert plan_slots({"kind": "ricorrente", "occurrences": [{"date": "2026-12-01"}]}, TODAY, st)[0] == "recurring_skipped"


def test_slot_past_midnight():
    assert Slot(date(2026, 12, 31), date(2026, 12, 31), "22:00", "02:00").wp_dates()[1] == "2027-01-01 02:00:00"


# ---------------------------------------------------------------- estrazione
def test_parse_page_and_links():
    html = """<html><head><meta property="og:image" content="/up/loc.jpg"><title>X</title></head>
    <body><nav>menu</nav><article><h1>Concerto di Natale</h1>
    <p>Sabato 12 dicembre alle 20.45 nella chiesa parrocchiale di Clusone. Ingresso libero. """ + "testo " * 50 + """</p>
    <img src="/up/logo.png"><img src="/up/foto.jpg"><a href="/up/programma.pdf">programma</a>
    <a href="https://calendar.google.com/calendar/render?action=TEMPLATE&dates=20261212T194500Z/20261212T214500Z">cal</a>
    </article><a href="/eventi/123/festa">festa</a><a href="https://altro.it/eventi/9/x">no</a></body></html>"""
    p = parse_page(html, "https://www.comune.test.it/eventi/1/concerto")
    assert p["title"] == "Concerto di Natale"
    assert p["images"][0] == "https://www.comune.test.it/up/loc.jpg"
    assert "https://www.comune.test.it/up/foto.jpg" in p["images"] and not any("logo" in i for i in p["images"])
    assert p["pdfs"] == ["https://www.comune.test.it/up/programma.pdf"]
    assert "20261212T194500Z" in p["text"] and "menu" not in p["text"]
    assert find_links(html, "https://www.comune.test.it/eventi", r"/eventi/\d+/") == ["https://www.comune.test.it/eventi/123/festa"]


def test_parse_json_with_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Ecco: {"a": 2} fine') == {"a": 2}


def test_pick_best_prefers_portrait_and_skips_small():
    small = Picture(b"a", "image/jpeg", 120, 120, "s")
    wide = Picture(b"b", "image/jpeg", 1200, 800, "w")
    poster = Picture(b"c", "image/jpeg", 900, 1270, "p")
    assert pick_best([small, wide, poster], 300).source_url == "p"
    assert pick_best([small], 300) is None


# ---------------------------------------------------------------- fonti
MUNI_LIST = [
    {"id": 1, "start_date": "2026-03-12", "end_date": "2026-03-12"},
    {"id": 2, "start_date": "2026-12-12", "end_date": "2026-12-12"},
]
MUNI_DETAIL = {
    "id": 2, "title": "Concerto di Natale", "content": "<p>Il coro si esibisce.</p>", "url": "https://x-api/event/2",
    "start_date": "2026-12-12", "end_date": "2026-12-12",
    "start_time": "2000-01-01T19:45:00Z", "start_time_with_timezone": "2010-01-01T20:45:00+01:00",
    "end_time": None, "address": "Via Roma 9, Clusone", "luogo": {"name": "Auditorium comunale"},
    "image": {"url": "/s3/20001/media/locandina.jpg", "i1440x1920": "/s3/1440x1920/s3/20001/media/locandina.jpg",
              "base_url": "http://municipium-images-production.s3-website-eu-west-1.amazonaws.com"},
    "has_image": True, "attachments": [{"url": "/s3/20001/allegati/programma.pdf"}], "costo": "Gratuito",
    "event_categories": [{"name": "Cultura"}],
}


def test_municipium_source():
    http = FakeHttp({"/api/site/v2/events/2": MUNI_DETAIL, "/api/site/v2/events": MUNI_LIST})
    src = MunicipiumSource({"id": "clusone", "api": "https://clusone-api.municipiumapp.it", "comune": "Clusone"}, http, TODAY)
    raws = src.fetch()
    assert len(raws) == 1
    r = raws[0]
    assert r.hints["start_time"] == "20:45" and r.hints["venue"] == "Auditorium comunale"
    assert r.image_urls[0] == "https://clusone-api.municipiumapp.it/s3/20001/media/locandina.jpg"
    assert r.pdf_urls == ["https://clusone-api.municipiumapp.it/s3/20001/allegati/programma.pdf"]
    assert "Costo: Gratuito" in r.text


def test_valseriana_source():
    post = {
        "id": 39993, "link": "https://www.valseriana.eu/eventi/christmas-yoga/",
        "title": {"rendered": "Christmas Yoga"}, "content": {"rendered": "<p>Corso gratuito</p>"},
        "_embedded": {
            "wp:featuredmedia": [{"source_url": "https://www.valseriana.eu/wp-content/uploads/christmas-yoga.jpg"}],
            "wp:term": [[{"taxonomy": "eventi_date", "name": "20261211"}, {"taxonomy": "eventi_date", "name": "20261204"}],
                        [{"taxonomy": "comuni", "name": "Onore", "slug": "onore"}]],
        },
    }
    old = {"id": 1, "link": "x", "title": {"rendered": "Vecchio"}, "content": {"rendered": ""},
           "_embedded": {"wp:term": [[{"taxonomy": "eventi_date", "name": "20250101"}]]}}
    http = FakeHttp({"/wp-json/wp/v2/eventi": [post, old]})
    raws = ValserianaSource({"id": "valseriana", "base_url": "https://www.valseriana.eu"}, http, TODAY).fetch()
    assert len(raws) == 1 and raws[0].hints["comune"] == "Onore"
    assert raws[0].hints["start_date"] == "2026-12-04" and raws[0].needs_page_fetch


# ---------------------------------------------------------------- pipeline completa (IA e WP finti)
class FakeLLM:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def analyze(self, raw, today, picture, pdf_text=""):
        self.calls += 1
        assert picture is not None and picture.portrait
        return self.data


class FakeWP:
    def __init__(self):
        self.events, self.media = [], []

    def check(self):
        pass

    def upload_media(self, data, filename, mime, title, alt, caption=""):
        self.media.append(filename)
        return 500

    def venue_id(self, v):
        return 10

    def organizer_id(self, o):
        return None

    def category_id(self, n):
        return 20

    def tag_id(self, n):
        return 30

    def find_existing(self, title, day):
        return None

    def create_event(self, payload):
        self.events.append(payload)
        return {"id": 1000 + len(self.events)}

    def update_event(self, i, payload):
        self.events.append(("update", i, payload))
        return {"id": i}

    def edit_link(self, i):
        return f"https://mep/wp-admin/post.php?post={i}"


def test_full_pipeline_creates_then_skips_and_dedups(st, tmp_path, monkeypatch):
    sources_file = tmp_path / "s.yaml"
    sources_file.write_text("sources:\n  - {id: clusone, type: municipium, api: 'https://clusone-api.municipiumapp.it', comune: Clusone, zona: Val Seriana, provincia: BG}\n")
    st.sources_file = sources_file
    monkeypatch.setattr("app.pipeline.telegram", lambda *a, **k: None)
    monkeypatch.setattr("app.pipeline.render_pdf", lambda http, url: (None, ""))

    ai = {"is_event": True, "title": "Concerto di Natale del coro", "kind": "singolo",
          "occurrences": [{"date": "2026-12-12", "start_time": "20:45", "end_time": None}],
          "venue": {"name": "Auditorium comunale", "address": "Via Roma 9", "city": "Clusone", "province": "BG"},
          "organizer": {"name": None}, "cost": "Ingresso libero", "category": "Musica e concerti",
          "excerpt": "Il coro in concerto.", "description_html": "<p>Testo</p><script>x</script>"}

    pl = Pipeline(st)
    pl.http = FakeHttp({"/api/site/v2/events/2": MUNI_DETAIL, "/api/site/v2/events": MUNI_LIST,
                        "locandina.jpg": png(800, 1130)})
    pl.llm = FakeLLM(ai)
    pl.wp = FakeWP()
    pl.run()
    assert len(pl.wp.events) == 1
    ev = pl.wp.events[0]
    assert ev["start_date"] == "2026-12-12 20:45:00" and ev["image"] == 500 and ev["status"] == "draft"
    assert "<script>" not in ev["description"] and "Fonte:" in ev["description"]
    assert ev["tags"] == [30] and ev["categories"] == [20] and ev["venue"] == 10

    # secondo giro: niente di nuovo, nessuna chiamata IA
    pl2 = Pipeline(st)
    pl2.http, pl2.llm, pl2.wp = pl.http, FakeLLM(ai), FakeWP()
    pl2.run()
    assert pl2.llm.calls == 0 and pl2.wp.events == []

    # stesso evento da un'altra fonte -> duplicato
    from app.models import RawEvent
    pl3 = Pipeline(st)
    pl3.http, pl3.llm, pl3.wp = pl.http, FakeLLM(ai), FakeWP()
    raw = RawEvent("valseriana", "Promoserio", "999", "https://www.valseriana.eu/eventi/x",
                   title="Concerto Natale", text="...", image_urls=["https://clusone-api.municipiumapp.it/s3/20001/media/locandina.jpg"],
                   hints={"comune": "Clusone"})
    assert pl3.process(raw, TODAY) is False
    assert pl3.report.skipped["duplicate"] == 1 and pl3.wp.events == []


def test_dry_run_prints(st, tmp_path, monkeypatch, capsys):
    sources_file = tmp_path / "s.yaml"
    sources_file.write_text("sources:\n  - {id: clusone, type: municipium, api: 'https://clusone-api.municipiumapp.it'}\n")
    st.sources_file = sources_file
    monkeypatch.setattr("app.pipeline.render_pdf", lambda http, url: (None, ""))
    pl = Pipeline(st, dry_run=True)
    pl.http = FakeHttp({"/api/site/v2/events/2": MUNI_DETAIL, "/api/site/v2/events": MUNI_LIST, "locandina.jpg": png(800, 1130)})
    pl.llm = FakeLLM({"is_event": True, "title": "T", "kind": "singolo", "occurrences": [{"date": "2026-12-12"}]})
    pl.run()
    out = json.loads(capsys.readouterr().out)
    assert out["slots"] == [["2026-12-12 00:00:00", "2026-12-12 23:59:59"]]


def test_siscom_relative_images_and_class_fallback():
    html = """<html><body><div class="page-header-wrapper"><div class="container">
    <h1>Mostra filatelica</h1><p>Dal 5 all'8 dicembre nella sala civica di Songavazzo una mostra di francobolli.</p>
    <p>Aperta dalle 10 alle 18, ingresso libero, a cura del circolo filatelico locale, con annullo speciale.</p>
    <img src="http://../../portals/1757/SiscomImmaginiNews/mostra.webp">
    <img src="https://maps.googleapis.com/maps/api/staticmap?center=1,2"></div></div></body></html>"""
    p = parse_page(html, "https://www.comune.songavazzo.bg.it/Dettaglionews?IDNews=1")
    assert "francobolli" in p["text"]
    assert p["images"] == ["https://www.comune.songavazzo.bg.it/portals/1757/SiscomImmaginiNews/mostra.webp"]


def test_web_endpoints(st, tmp_path, monkeypatch):
    import threading, urllib.request, base64
    from http.server import ThreadingHTTPServer
    from app.web import App, make_handler
    from app.store import Store
    sf = tmp_path / "s.yaml"
    sf.write_text("sources:\n  - {id: clusone, type: municipium, api: 'x', name: Comune di Clusone}\n")
    st.sources_file = sf
    s = Store(st.data_dir)
    rid = s.start_run("test")
    s.save("clusone", "1", url="u", title="Concerto", status="created", wp_ids=[5], event_date="2026-12-12", city="Clusone")
    s.finish_run(rid, "ok", created=1, per_source={"clusone": {"trovati": 3, "nuovi": 1, "errori": 0}}, report="<b>ok</b>")
    calls = []
    st.web_password = "pw"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(st, lambda src, dry: calls.append((src, dry)) or True)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    auth = {"Authorization": "Basic " + base64.b64encode(b"admin:pw").decode()}
    def get(p, h=auth):
        return urllib.request.urlopen(urllib.request.Request(base + p, headers=h))
    with pytest.raises(urllib.error.HTTPError):
        get("/api/status", {})
    assert b"MEP Eventi" in get("/").read()
    stt = json.loads(get("/api/status").read())
    assert stt["counts"]["by_status"]["created"] == 1 and stt["last_run"]["per_source"]["clusone"]["trovati"] == 3
    items = json.loads(get("/api/items?status=created").read())
    assert items[0]["wp_ids"] == [5]
    req = urllib.request.Request(base + "/api/run", data=b'{"source":"clusone","dry":true}', headers=auth | {"Content-Type": "application/json"}, method="POST")
    assert json.loads(urllib.request.urlopen(req).read())["started"] and calls == [("clusone", True)]
    srv.shutdown()
