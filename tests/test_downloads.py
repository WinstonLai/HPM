import json
from pathlib import Path

import pytest

import datagovsg
import osm
import provenance


def geojson(n=2):
    return json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature"}] * n}).encode()


@pytest.mark.parametrize("name,content,ok", [
    ("a.geojson", geojson(), True),
    ("a.geojson", geojson(0), False),                    # no features
    ("a.geojson", b'{"type": "Feature', False),          # truncated write
    ("a.geojson", b"<html>429 Too Many Requests</html>", False),
    ("a.geojson", b"[1, 2]", False),                     # valid JSON, wrong shape
    ("a.csv", b"id,name\n1,x\n", True),
    ("a.csv", b"id,name\n", False),                      # header only
    ("a.csv", b"<!doctype html>\n<html>,x\n", False),
])
def test_is_valid_download(tmp_path, name, content, ok):
    path = tmp_path / name
    path.write_bytes(content)
    assert datagovsg.is_valid_download(path) is ok


def test_missing_file_is_invalid(tmp_path):
    assert datagovsg.is_valid_download(tmp_path / "nope.geojson") is False


def test_write_validated_keeps_the_old_file_when_the_new_content_is_bad(tmp_path):
    dest = tmp_path / "d.geojson"
    dest.write_bytes(geojson())
    with pytest.raises(datagovsg.DownloadError):
        datagovsg.write_validated(dest, lambda tmp: tmp.write_bytes(b"<html>error</html>"))
    assert dest.read_bytes() == geojson()
    assert [p.name for p in tmp_path.iterdir()] == ["d.geojson"]        # no .part left behind


def test_write_validated_cleans_up_after_a_crash_mid_write(tmp_path):
    dest = tmp_path / "d.geojson"

    def crash(tmp: Path):
        tmp.write_bytes(b'{"features": [')
        raise OSError("disk full")

    with pytest.raises(OSError):
        datagovsg.write_validated(dest, crash)
    assert list(tmp_path.iterdir()) == []                                # nothing cached to be trusted later


def test_fetch_dataset_redownloads_an_invalid_cache_and_reuses_a_valid_one(tmp_path, monkeypatch):
    monkeypatch.setattr(datagovsg, "RAW_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(datagovsg, "_poll_download_url", lambda dataset_id: calls.append(dataset_id) or "https://x/y")

    class Resp:
        content = geojson()

    monkeypatch.setattr(datagovsg, "_get_with_retries", lambda *a, **k: Resp())
    (tmp_path / "d.geojson").write_bytes(b'{"features": [')              # truncated earlier run
    path = datagovsg.fetch_dataset("d_1", "d.geojson")
    assert calls == ["d_1"] and datagovsg.is_valid_download(path)
    datagovsg.fetch_dataset("d_1", "d.geojson")
    assert calls == ["d_1"]                                              # valid cache: no second download


def test_osm_empty_overpass_answer_is_a_failure_not_an_empty_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(osm, "RAW_DIR", tmp_path)
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"elements": [], "remark": "runtime error: Query timed out"}

    monkeypatch.setattr(osm.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError):
        osm.fetch_osm("osm_fitness.geojson", attempts=2)
    assert list(tmp_path.iterdir()) == []


def test_download_all_reports_failures(monkeypatch):
    monkeypatch.setattr(osm, "fetch_osm", lambda filename, force=False: (_ for _ in ()).throw(RuntimeError("down")))
    assert sorted(osm.download_all()) == sorted(osm.QUERIES)


def test_redirect_processed_dir_repoints_stages_and_meta(tmp_path, monkeypatch):
    class Stage:
        PROCESSED_DIR = Path("/real/data/processed")

    monkeypatch.setattr(provenance, "PROCESSED_DIR", provenance.PROCESSED_DIR)
    monkeypatch.setattr(provenance, "META_PATH", provenance.META_PATH)
    stage = Stage()
    out = provenance.redirect_processed_dir(tmp_path / "scratch", stage)
    assert stage.PROCESSED_DIR == out == tmp_path / "scratch" and out.is_dir()
    assert provenance.META_PATH == out / "_meta.json"
