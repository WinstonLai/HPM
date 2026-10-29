import ast
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

import datagovsg
import osm
import useragent

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "lib"))

import build_mall_registry as registry  # noqa: E402
import data_loader  # noqa: E402


def test_user_agent_identifies_the_project_and_takes_an_optional_contact(monkeypatch):
    monkeypatch.delenv("HPM_CONTACT", raising=False)
    ua = useragent.user_agent()
    assert useragent.PROJECT_URL in ua
    monkeypatch.setenv("HPM_CONTACT", " me@example.org ")
    assert useragent.user_agent().endswith("; me@example.org)")


def test_http_clients_use_the_shared_user_agent():
    assert osm.HEADERS["User-Agent"].startswith("HPM-readiness-poc/1.0 (+")
    assert registry.HEADERS == osm.HEADERS or registry.HEADERS["User-Agent"].startswith("HPM-readiness-poc/1.0 (+")


def _runs_on_import(node: ast.stmt) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return False
    if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):     # `if __name__ == "__main__":`
        return False
    return True


def test_no_etl_module_creates_directories_when_imported():
    for path in sorted((ROOT / "etl").glob("*.py")):
        for node in filter(_runs_on_import, ast.parse(path.read_text()).body):
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "mkdir"]
            assert not calls, f"{path.name}:{node.lineno} creates a directory at import time"


def test_write_validated_creates_the_destination_directory(tmp_path):
    dest = tmp_path / "not" / "yet" / "d.csv"
    datagovsg.write_validated(dest, lambda tmp: tmp.write_text("a,b\n1,2\n"))
    assert dest.read_text() == "a,b\n1,2\n"


@pytest.fixture
def processed(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loader, "PROCESSED_DIR", tmp_path)
    st.cache_data.clear()
    yield tmp_path
    st.cache_data.clear()


def test_loaders_pick_up_a_rebuilt_csv_without_a_restart(processed):
    path = processed / "hpm_index.csv"
    path.write_text("mall_id,hpm_index\na,1.0\n")
    assert data_loader.load_default_index()["hpm_index"].tolist() == [1.0]
    path.write_text("mall_id,hpm_index\na,2.0\nb,3.0\n")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 5_000_000_000))
    assert data_loader.load_default_index()["hpm_index"].tolist() == [2.0, 3.0]


def test_meta_is_reread_when_it_changes_and_empty_when_missing(processed):
    assert data_loader.load_meta() == {}
    meta = processed / "_meta.json"
    meta.write_text('{"a": 1}')
    assert data_loader.load_meta() == {"a": 1}
    meta.write_text('{"a": 2}')
    os.utime(meta, ns=(meta.stat().st_atime_ns, meta.stat().st_mtime_ns + 5_000_000_000))
    assert data_loader.load_meta() == {"a": 2}


def test_postal_codes_keep_their_leading_zeros(processed):
    (processed / "malls.csv").write_text("mall_id,name,aliases,postal_code\na,A,,018956\nb,B,Bee; Bea,238801\n")
    assert data_loader._csv("malls.csv")["postal_code"].tolist() == ["018956", "238801"]
    assert data_loader.load_aliases().to_dict() == {"a": "", "b": "Bee; Bea"}
