"""signboard-14 处一：甲路径——求值星期不匹配须正式空播并记拒播痕。

夹具「工作日求值周末窗发布」：会议导览屏 scr_meet_d1 绑定 win_weekend（星期 6,7），
工作日（星期 1～5）在开放钟点内求值也必须空播，且：
  - 正式求值结果册 eval_ledger 不得写入任何清单行（只能写 blank 行或不写）；
  - 变更历史须留下 reject_weekday 拒播痕；
  - 匹配星期（6/7）且钟点在窗内才吐清单，并在册中落 playlist 行。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PYTHONPATH", str(ROOT / "backend"))

from db import connect, init_db, reset_connections  # noqa: E402
from app import app  # noqa: E402

FIXTURE_NAME = "工作日求值周末窗发布"


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    reset_connections()
    db = tmp_path / "app.db"
    monkeypatch.setattr("db.DB_PATH", db)
    monkeypatch.setattr("db.DATA", tmp_path)
    if db.exists():
        db.unlink()
    init_db()
    yield
    reset_connections()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _login(client, username="admin", password="admin123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _meet_screen(client, h):
    screens = client.get("/api/screens", headers=h).json()["items"]
    return next(s for s in screens if s["code"] == "scr_meet_d1")


def _ledger_rows(screen_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_ledger WHERE screen_id=? ORDER BY id",
            (screen_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def test_fixture_weekday_eval_weekend_window_publishes_nothing_on_workday(client):
    """夹具点名：工作日对周末窗发布求值——必须空播。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    # 钟点 11:00 落在 win_weekend 的 10:00-18:00 内，仅星期不匹配
    ev = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "3"},
    )
    assert ev.status_code == 200, ev.text
    body = ev.json()
    # 正式求值结果为空播
    assert body["play"] is None
    assert body["source"] == "publication"
    assert body["gate_status"] == "rejected_weekday"
    # 册中不得写入清单行
    rows = _ledger_rows(screen["id"])
    assert not any(r["result_kind"] == "playlist" for r in rows), rows
    assert all(r["result_kind"] == "blank" for r in rows), rows


def test_reject_leaves_history_trace(client):
    """甲路径拒播必须在变更历史留痕，动作固定为 reject_weekday。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "1"},
    )
    history = client.get("/api/history", headers=h).json()["items"]
    traces = [x for x in history if x["action"] == "reject_weekday"]
    assert traces, "星期不匹配空播须记拒播痕"
    assert any(str(screen["id"]) in t["detail"] and "周末开放" in t["detail"] for t in traces), traces


def test_matching_weekday_returns_playlist_and_ledges_it(client):
    """匹配星期且钟点在窗内：吐清单，正式结果册写 playlist 行。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    ev = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "6"},
    )
    assert ev.status_code == 200, ev.text
    body = ev.json()
    assert body["gate_status"] == "played"
    assert body["play"] is not None
    assert body["play"]["kind"] == "playlist"
    assert len(body["play"]["items"]) >= 1
    rows = _ledger_rows(screen["id"])
    assert any(r["result_kind"] == "playlist" and r["weekday"] == "6" for r in rows), rows


def test_window_weekday_set_is_source_of_truth(client):
    """时段窗星期集合被忽略即 bug：对 1..5 全部工作日逐天空播，6/7 才放行。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    for wd in ("1", "2", "3", "4", "5"):
        ev = client.post(
            "/api/evaluate/screen",
            headers=h,
            json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": wd},
        ).json()
        assert ev["play"] is None, wd
        assert ev["gate_status"] == "rejected_weekday", wd
    for wd in ("6", "7"):
        ev = client.post(
            "/api/evaluate/screen",
            headers=h,
            json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": wd},
        ).json()
        assert ev["play"] is not None, wd
        assert ev["gate_status"] == "played", wd
