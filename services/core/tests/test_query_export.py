"""Query engine, views (FR-5, FR-6), review queue, export/import round trips (FR-9)."""

from folio_core.domain.models import ClaimStatus, Extractor
from folio_core.store import repo

from .conftest import drain, make_container


def _ingest(c, files):
    c.ingestion.add_root(str(files))
    drain(c)


def test_hybrid_search_and_entity_card(container, files):
    _ingest(container, files)
    hits = container.search.search("Acme contract signed", k=5)
    assert hits and any("signed" in h["text"] for h in hits)
    assert hits[0]["locator"]["kind"] in ("page", "text", "time")

    priya = repo.search_entities(container.db.reader(), "priya")[0]
    card = container.cards.card(priya.id)
    assert "owns" in card["groups"] and "email" in card["groups"]
    ev = card["groups"]["owns"][0]["evidence"][0]
    assert ev["source_id"] and ev["locator"]["kind"] == "text"
    assert card["files"]


def test_views_share_one_model(container, files):
    _ingest(container, files)
    conn = container.db.reader()
    acme = repo.search_entities(conn, "Acme Contract", ["Contract"])[0]
    g = container.views.graph(acme.id, depth=2)
    assert any(e["predicate"] == "owns" for e in g["edges"])
    tl = container.views.timeline(acme.id)
    dates = [i["valid_from"] for i in tl["items"]]
    assert dates and dates == sorted(dates)
    sw = container.views.swimlane("type")
    assert {lane["id"] for lane in sw["lanes"]} >= {"Contract"}

    # An edit anywhere is visible everywhere: reject the edge, the graph drops it.
    owns = next(e for e in g["edges"] if e["predicate"] == "owns")
    container.knowledge.set_claim_status([owns["id"]], ClaimStatus.REJECTED)
    assert not any(e["id"] == owns["id"] for e in container.views.graph(acme.id)["edges"])


def test_review_queue_surfaces_conflicts_first(container):
    k = container.knowledge
    contract = k.create_entity("Contract", "Acme")
    for day in ("March 3, 2026", "March 4, 2026"):
        cid = k.add_claim(subject_id=contract.id, predicate="signed_on", value=day,
                          status=ClaimStatus.VERIFIED, extractor=Extractor(kind="user"))
    with container.ledger.group("system", "test") as tx:
        tx.update("claims", cid, {"status": "proposed", "confidence": 0.4})
    q = container.review.queue()
    assert q["conflicts"] and q["conflicts"][0]["predicate"] == "signed_on"


def _snapshot(c):
    conn = c.db.reader()
    out = {}
    for table in ("entities", "aliases", "claims", "evidence", "labels"):
        out[table] = sorted(tuple(sorted(dict(r).items())) for r in conn.execute(f"SELECT * FROM {table}"))
    return out


def test_json_round_trip_loses_nothing(container, files, tmp_path):
    _ingest(container, files)
    data = container.exporter.to_json()
    other = make_container(tmp_path / "restore")
    other.exporter.from_json(data)
    assert _snapshot(other) == _snapshot(container)
    groups = {r[0] for r in other.db.reader().execute("SELECT id FROM event_groups")}
    assert {g["id"] for g in data["event_groups"]} <= groups  # full provenance kept


def test_graphml_round_trip_loses_nothing(container, files, tmp_path):
    _ingest(container, files)
    xml = container.exporter.to_graphml()
    other = make_container(tmp_path / "restore")
    other.exporter.from_graphml(xml)
    a, b = _snapshot(container), _snapshot(other)
    for table in ("entities", "aliases", "claims", "evidence"):
        assert a[table] == b[table], table


def test_markdown_and_csv_exports(container, files):
    _ingest(container, files)
    md = container.exporter.to_markdown()
    assert "### Priya Sharma" in md and "owns → Acme Contract" in md
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(container.exporter.to_csv_zip()))
    assert set(z.namelist()) == {"entities.csv", "aliases.csv", "claims.csv", "evidence.csv"}


def test_golden_set_meets_precision_gate():
    from pathlib import Path

    from folio_core.evaluation import run_eval

    report = run_eval(Path(__file__).resolve().parents[3] / "eval" / "golden")
    assert report["precision"] >= 0.8
