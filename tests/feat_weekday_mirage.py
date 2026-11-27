"""signboard-14 处二：假绿跨服务落点——错星期求值不得被任何页面当成命中绿。

夹具同为「工作日求值周末窗发布」。本文件盯发布链路与屏幕/时段侧的可见性：
  - 正式发布列表必须携带所绑时段窗的星期集合与门限判定字段，前端不得硬染命中绿；
  - 错星期求值后，屏幕侧最近求值状态必须显式呈现 rejected_weekday（红/拒），
    不得回显 played 假绿；
  - 同事务跨表账实：eval_ledger 与 change_history 在一次求值内一致。
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


def test_publish_official_exposes_window_weekdays_not_fake_green(client):
    """发布列表须联表带出时段星期集合，供门限判定，不能让页面盲染绿。"""
    h = _login(client)
    items = client.get("/api/publish/official", headers=h).json()["items"]
    meet = next(p for p in items if p["screen_code"] == "scr_meet_d1")
    assert meet["window_weekdays"] == "6,7"
    # 门限字段须显式给出，禁止缺省即绿
    assert meet["weekday_gate"] == "6,7"
    assert meet["gate_status_for"] is not None


def test_screen_shows_rejected_state_after_workday_eval(client):
    """错星期求值后，屏幕台账侧最近求值状态须为 rejected_weekday，不得假绿。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    ev = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "2"},
    ).json()
    assert ev["play"] is None
    screens = client.get("/api/screens", headers=h).json()["items"]
    refreshed = next(s for s in screens if s["id"] == screen["id"])
    assert refreshed["last_eval_gate"] == "rejected_weekday"
    assert refreshed["last_eval_weekday"] == "2"
    # 绝不允许回显 played
    assert refreshed["last_eval_gate"] != "played"


def test_ledger_and_history_are_consistent_in_one_transaction(client):
    """同事务跨表账实：一次错星期求值，册中 blank 行与历史拒播痕同时出现。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "4"},
    )
    with connect() as conn:
        blank = conn.execute(
            "SELECT COUNT(*) c FROM eval_ledger WHERE screen_id=? AND result_kind='blank'",
            (screen["id"],),
        ).fetchone()["c"]
        listed = conn.execute(
            "SELECT COUNT(*) c FROM eval_ledger WHERE screen_id=? AND result_kind='playlist'",
            (screen["id"],),
        ).fetchone()["c"]
        traces = conn.execute(
            "SELECT COUNT(*) c FROM change_history WHERE action='reject_weekday' AND entity_id=?",
            (screen["id"],),
        ).fetchone()["c"]
    assert blank == 1 and listed == 0
    assert traces == 1, "拒播痕须与正式空播同事务落账"


def test_windows_list_carries_weekday_set_for_gate_check(client):
    """时段窗页的数据须回传星期集合，门限判断只认真实集合。"""
    h = _login(client)
    windows = client.get("/api/windows", headers=h).json()["items"]
    weekend = next(w for w in windows if w["code"] == "win_weekend")
    assert set(weekend["weekdays"].split(",")) == {"6", "7"}
    assert weekend["gate_status_for"] is not None
