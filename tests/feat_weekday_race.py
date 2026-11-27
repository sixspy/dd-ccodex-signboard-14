"""signboard-14 处三：抢锁点「同屏求值星期互斥」。

同一块会议屏同时进来两路求值（一路工作日、一路周末日），正式求值结果册只允许
一方写入；败方须收到 409 锁冲突，且对正式区零改动（无 eval_ledger 行、无拒播痕）。
两路无锁双成即红。
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PYTHONPATH", str(ROOT / "backend"))

from db import connect, init_db, reset_connections  # noqa: E402
from app import app  # noqa: E402
from locks import acquire, release  # noqa: E402

LOCK_KEY_TMPL = "eval_weekday:screen:{screen_id}"
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
    # 提高 SQLite 并发下的锁竞争可见性
    with connect() as conn:
        conn.execute("PRAGMA busy_timeout=5000")
    yield
    # 清残留锁，避免用例间污染
    with connect() as conn:
        conn.execute("DELETE FROM write_locks")
        conn.commit()
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


def _eval(client, h, screen_id: int, weekday: str, barrier: threading.Barrier, results: dict, tag: str):
    barrier.wait()
    r = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen_id, "now_hm": "11:00", "weekday": weekday},
    )
    results[tag] = {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}


def test_concurrent_same_screen_eval_is_mutex(client):
    """两路并发同屏求值：一成一 409，败方零正式改。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    barrier = threading.Barrier(2)
    results: dict = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_eval, client, h, screen["id"], "3", barrier, results, "workday")
        f2 = pool.submit(_eval, client, h, screen["id"], "6", barrier, results, "weekend")
        f1.result(timeout=15)
        f2.result(timeout=15)

    statuses = sorted(v["status"] for v in results.values())
    assert statuses == [200, 409], results
    winner = next(v for v in results.values() if v["status"] == 200)
    loser = next(v for v in results.values() if v["status"] == 409)
    assert "锁定" in loser["body"]["detail"] or "锁" in loser["body"]["detail"]

    with connect() as conn:
        ledger = [dict(r) for r in conn.execute(
            "SELECT * FROM eval_ledger WHERE screen_id=?", (screen["id"],)
        ).fetchall()]
    # 只有胜方落了恰好一行正式结果
    assert len(ledger) == 1, ledger
    if winner["body"].get("gate_status") == "played":
        assert ledger[0]["result_kind"] == "playlist"
    else:
        assert ledger[0]["result_kind"] == "blank"


def test_lock_released_after_eval_allows_next_writer(client):
    """求值结束即放锁，后续同屏求值可正常获得锁（无死锁）。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    first = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "6"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/evaluate/screen",
        headers=h,
        json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "7"},
    )
    assert second.status_code == 200, second.text
    with connect() as conn:
        held = conn.execute(
            "SELECT COUNT(*) c FROM write_locks WHERE lock_key=?",
            (LOCK_KEY_TMPL.format(screen_id=screen["id"]),),
        ).fetchone()["c"]
    assert held == 0, "求值完成后必须释放星期互斥锁"


def test_external_lock_holder_blocks_eval_with_zero_official_change(client):
    """他人持锁期间求值必须 409，且正式册零写入。"""
    h = _login(client)
    screen = _meet_screen(client, h)
    key = LOCK_KEY_TMPL.format(screen_id=screen["id"])
    acquire(key, "someone_else")
    try:
        r = client.post(
            "/api/evaluate/screen",
            headers=h,
            json={"screen_id": screen["id"], "now_hm": "11:00", "weekday": "3"},
        )
        assert r.status_code == 409
        with connect() as conn:
            ledger_cnt = conn.execute(
                "SELECT COUNT(*) c FROM eval_ledger WHERE screen_id=?", (screen["id"],)
            ).fetchone()["c"]
            trace_cnt = conn.execute(
                "SELECT COUNT(*) c FROM change_history WHERE action='reject_weekday' AND entity_id=?",
                (screen["id"],),
            ).fetchone()["c"]
        assert ledger_cnt == 0 and trace_cnt == 0, "败方零正式改"
    finally:
        release(key, "someone_else")
