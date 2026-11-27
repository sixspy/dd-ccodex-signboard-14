"""在线求值：某屏此刻应播什么。

signboard-14：求值时刻的星期若不在时段窗星期集合内，必须正式空播（甲路径），
并在同一事务内写 eval_ledger(blank) 与 change_history(reject_weekday)；
同屏求值经 write_locks 的 eval_weekday:screen:{id} 互斥，败方零正式改。
"""
from __future__ import annotations

import time
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect, rows_to_list
from locks import acquire, release
from validators import require_hm, require_positive_int, window_covers

router = APIRouter(prefix="/api/evaluate", tags=["evaluate"])


def _weekday_set(window) -> set[str]:
    return set((window["weekdays"] or "").split(","))


@router.post("/screen")
def evaluate_screen(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    screen_id = require_positive_int(body.get("screen_id"), "屏幕编号")
    now_hm = require_hm(body.get("now_hm") or datetime.now().strftime("%H:%M"), "求值时刻")
    weekday = str(body.get("weekday") or datetime.now().isoweekday())
    if weekday not in {"1", "2", "3", "4", "5", "6", "7"}:
        raise HTTPException(400, "星期须为 1～7")

    # 抢锁点：同屏求值星期互斥。败方在此 409，对正式区零改动。
    lock_key = f"eval_weekday:screen:{screen_id}"
    holder = f"{user['username']}@{time.time_ns()}"
    acquire(lock_key, holder)
    try:
        return _evaluate_locked(screen_id, now_hm, weekday, user["username"], lock_key, holder)
    finally:
        release(lock_key, holder)


def _write_ledger(conn, *, screen_id, publication_id, window_id, weekday, now_hm,
                  result_kind, gate_status, reason, item_count, actor) -> int:
    cur = conn.execute(
        """
        INSERT INTO eval_ledger(screen_id,publication_id,window_id,weekday,now_hm,
                                result_kind,gate_status,reason,item_count,actor,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (screen_id, publication_id, window_id, weekday, now_hm,
         result_kind, gate_status, reason, item_count, actor, time.time()),
    )
    return cur.lastrowid


def _evaluate_locked(screen_id, now_hm, weekday, actor, lock_key, holder) -> dict:
    with connect() as conn:
        # 覆盖优先：覆盖条目本身即正式指令，不走时段星期门限，也不占正式结果册
        screen = conn.execute("SELECT * FROM screens WHERE id=?", (screen_id,)).fetchone()
        if not screen:
            raise HTTPException(404, "屏幕不存在")
        ov = conn.execute(
            "SELECT * FROM overrides WHERE screen_id=? AND official=1 AND active=1 ORDER BY id DESC LIMIT 1",
            (screen_id,),
        ).fetchone()
        if ov:
            result = {
                "source": "override",
                "effect": ov["effect"],
                "playlist_id": ov["playlist_id"],
                "asset_id": ov["asset_id"],
                "now_hm": now_hm,
                "weekday": weekday,
                "gate_status": "override",
            }
            if ov["effect"] == "force_blank":
                result["play"] = None
            elif ov["effect"] == "force_asset" and ov["asset_id"]:
                asset = conn.execute("SELECT * FROM assets WHERE id=?", (ov["asset_id"],)).fetchone()
                result["play"] = {"kind": "asset", "asset": dict(asset) if asset else None}
            elif ov["effect"] == "force_playlist" and ov["playlist_id"]:
                items = rows_to_list(
                    conn.execute(
                        "SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY seq",
                        (ov["playlist_id"],),
                    ).fetchall()
                )
                result["play"] = {"kind": "playlist", "items": items}
            conn.commit()
            return result

        # 联查正式发布与时段窗星期集合（同事务跨表账实，禁止忽略星期集合）
        pub = conn.execute(
            """
            SELECT p.*, w.weekdays window_weekdays, w.start_hm window_start,
                   w.end_hm window_end, w.title window_title
            FROM publications p JOIN time_windows w ON w.id=p.window_id
            WHERE p.screen_id=? AND p.official=1 AND p.status='published'
            """,
            (screen_id,),
        ).fetchone()
        if not pub:
            ledger_id = _write_ledger(
                conn, screen_id=screen_id, publication_id=None, window_id=None,
                weekday=weekday, now_hm=now_hm, result_kind="blank",
                gate_status="no_publication", reason="无正式发布",
                item_count=0, actor=actor,
            )
            conn.execute(
                "INSERT INTO change_history(entity_kind,entity_id,action,detail,actor,created_at) "
                "VALUES('eval_ledger',?, 'reject_no_publication', ?, ?, ?)",
                (ledger_id, f"屏幕{screen_id} 无正式发布，正式空播", actor, time.time()),
            )
            conn.commit()
            return {
                "source": "empty", "play": None, "now_hm": now_hm,
                "weekday": weekday, "gate_status": "no_publication",
                "reason": "无正式发布", "ledger_id": ledger_id,
            }

        window = conn.execute(
            "SELECT * FROM time_windows WHERE id=?", (pub["window_id"],),
        ).fetchone()

        # 门限一：星期不匹配 → 正式空播 + 拒播痕，同一事务
        if weekday not in _weekday_set(window):
            reason = f"非开放星期（求值星期{weekday}，窗星期集合 {window['weekdays']}）"
            ledger_id = _write_ledger(
                conn, screen_id=screen_id, publication_id=pub["id"], window_id=window["id"],
                weekday=weekday, now_hm=now_hm, result_kind="blank",
                gate_status="rejected_weekday", reason=reason,
                item_count=0, actor=actor,
            )
            conn.execute(
                "INSERT INTO change_history(entity_kind,entity_id,action,detail,actor,created_at) "
                "VALUES('screen', ?, 'reject_weekday', ?, ?, ?)",
                (
                    screen_id,
                    f"屏幕{screen_id} 时段窗「{window['title']}」星期集合{window['weekdays']} "
                    f"不含求值星期{weekday}，正式空播（ledger#{ledger_id}）",
                    actor,
                    time.time(),
                ),
            )
            conn.commit()
            return {
                "source": "publication", "play": None, "reason": "非开放星期",
                "now_hm": now_hm, "weekday": weekday,
                "gate_status": "rejected_weekday",
                "window_weekdays": window["weekdays"], "ledger_id": ledger_id,
            }

        # 门限二：钟点不在窗内 → 正式空播（同样落账，保持账实）
        if not window_covers(window["start_hm"], window["end_hm"], now_hm):
            reason = f"不在时段窗内（{window['start_hm']}-{window['end_hm']}，求值 {now_hm}）"
            ledger_id = _write_ledger(
                conn, screen_id=screen_id, publication_id=pub["id"], window_id=window["id"],
                weekday=weekday, now_hm=now_hm, result_kind="blank",
                gate_status="outside_window", reason=reason,
                item_count=0, actor=actor,
            )
            conn.commit()
            return {
                "source": "publication", "play": None, "reason": "不在时段窗内",
                "now_hm": now_hm, "weekday": weekday,
                "gate_status": "outside_window",
                "window_weekdays": window["weekdays"], "ledger_id": ledger_id,
            }

        items = rows_to_list(
            conn.execute(
                """
                SELECT i.*, a.code asset_code, a.title asset_title, a.kind
                FROM playlist_items i JOIN assets a ON a.id=i.asset_id
                WHERE i.playlist_id=? ORDER BY i.seq
                """,
                (pub["playlist_id"],),
            ).fetchall()
        )
        # 正式命中：清单行入册（同事务）
        ledger_id = _write_ledger(
            conn, screen_id=screen_id, publication_id=pub["id"], window_id=window["id"],
            weekday=weekday, now_hm=now_hm, result_kind="playlist",
            gate_status="played", reason="命中时段窗",
            item_count=len(items), actor=actor,
        )
        conn.commit()
        return {
            "source": "publication",
            "version": pub["version"],
            "playlist_id": pub["playlist_id"],
            "window_id": pub["window_id"],
            "play": {"kind": "playlist", "items": items},
            "now_hm": now_hm,
            "weekday": weekday,
            "gate_status": "played",
            "window_weekdays": window["weekdays"],
            "ledger_id": ledger_id,
        }
