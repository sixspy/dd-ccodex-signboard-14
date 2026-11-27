"""并发双路命令 race_weekday_gate。

对同一块会议屏（scr_meet_d1，绑周末窗 win_weekend）同屏并发发起两路求值：
  - 工作日路（weekday=3）：本应被星期门限判空播；
  - 周末日路（weekday=6）：本应命中播放清单。
抢锁点「同屏求值星期互斥」要求两路只允许一方写入正式求值结果册：
  一成（200）一败（409），败方对正式区零改动；两路皆成即判定失败。

用法：
    PYTHONPATH=backend python scripts/race_weekday_gate.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
from app import app  # noqa: E402

SCREEN_CODE = "scr_meet_d1"
LOCK_KEY_TMPL = "eval_weekday:screen:{screen_id}"


def _login(client: TestClient) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="race_weekday_"))
    db.reset_connections()
    db.DB_PATH = tmp / "app.db"
    db.DATA = tmp
    db.init_db()

    with TestClient(app) as client:
        headers = _login(client)
        screen = next(
            s for s in client.get("/api/screens", headers=headers).json()["items"]
            if s["code"] == SCREEN_CODE
        )
        screen_id = screen["id"]
        barrier = threading.Barrier(2)
        results: dict = {}

        def _fire(tag: str, weekday: str) -> None:
            barrier.wait()
            r = client.post(
                "/api/evaluate/screen",
                headers=headers,
                json={"screen_id": screen_id, "now_hm": "11:00", "weekday": weekday},
            )
            results[tag] = {"status": r.status_code, "body": r.json()}

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_fire, "workday", "3")
            f2 = pool.submit(_fire, "weekend", "6")
            f1.result(timeout=20)
            f2.result(timeout=20)

        with db.connect() as conn:
            ledger = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, weekday, result_kind, gate_status FROM eval_ledger WHERE screen_id=?",
                    (screen_id,),
                ).fetchall()
            ]
            locks_left = [
                dict(r)
                for r in conn.execute(
                    "SELECT lock_key, holder FROM write_locks WHERE lock_key=?",
                    (LOCK_KEY_TMPL.format(screen_id=screen_id),),
                ).fetchall()
            ]

    print("== race_weekday_gate 同屏求值星期互斥 ==")
    for tag, r in results.items():
        print(f"  {tag:8s} HTTP {r['status']}  gate={r['body'].get('gate_status')}")
    print("  正式结果册行数:", len(ledger), ledger)
    print("  残留锁:", locks_left)

    statuses = sorted(r["status"] for r in results.values())
    ok = statuses == [200, 409] and len(ledger) == 1 and not locks_left
    if ok:
        print("收口：一成一败，败方零正式改，无锁双成未发生。")
        return 0
    print("失败：未达成同屏求值星期互斥（疑似无锁双成或锁未释放）。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
