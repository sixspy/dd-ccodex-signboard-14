"""写入短锁，防并发双写。

两层互斥并用：
  1. 进程内闸门（threading.Lock，按 lock_key 分键）：同进程并发请求在闸门处
     立即分胜负，败方 409，零正式改。SQLite（含 WAL）允许两个连接同时进入
     RESERVED 写事务，单靠行级 SELECT/INSERT 存在快照时序窗口，故必须有闸门。
  2. DB 行锁（write_locks 表，BEGIN IMMEDIATE）：跨进程/多 worker 的 TTL 互斥
     与持有者审计依据，闸门放行后仍校验行锁，他人有效持锁同样 409。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from fastapi import APIRouter, Header, HTTPException

from auth import current_user, require_writer
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])

_GATE_LOCK = threading.Lock()
_GATES: dict[str, threading.Lock] = {}
# 记录每个键当前的进程内持有者，供 release 精确放行
_GATE_HOLDERS: dict[str, str] = {}


def _gate_for(lock_key: str) -> threading.Lock:
    with _GATE_LOCK:
        return _GATES.setdefault(lock_key, threading.Lock())


def acquire(lock_key: str, holder: str, ttl_sec: int = 20) -> None:
    """同屏资源互斥：进程内闸门先分胜负，DB 行锁再兜底，禁止无锁双成。"""
    gate = _gate_for(lock_key)
    if not gate.acquire(blocking=False):
        # 同进程已有一路在临界区，败方立即 409，对正式区零改动
        with _GATE_LOCK:
            keeper = _GATE_HOLDERS.get(lock_key, "并发争用")
        raise HTTPException(409, f"资源锁定中：{keeper}")

    now = time.time()
    expires_at = now + ttl_sec
    conn = connect()
    try:
        # BEGIN IMMEDIATE：跨进程/多 worker 串行化，行锁兜底
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT holder, expires_at FROM write_locks WHERE lock_key=?",
            (lock_key,),
        ).fetchone()
        if row is not None and row["expires_at"] > now and row["holder"] != holder:
            conn.rollback()
            gate.release()
            raise HTTPException(409, f"资源锁定中：{row['holder']}")
        try:
            conn.execute(
                "INSERT INTO write_locks(lock_key,holder,expires_at) VALUES(?,?,?) "
                "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at",
                (lock_key, holder, expires_at),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            gate.release()
            raise HTTPException(409, "资源锁定中：并发争用失败") from exc
        with _GATE_LOCK:
            _GATE_HOLDERS[lock_key] = holder
    except HTTPException:
        raise
    except sqlite3.OperationalError as exc:
        conn.rollback()
        gate.release()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise HTTPException(409, "资源锁定中：并发争用失败") from exc
        raise
    finally:
        conn.close()


def release(lock_key: str, holder: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "DELETE FROM write_locks WHERE lock_key=? AND holder=?",
            (lock_key, holder),
        )
        conn.commit()
    finally:
        conn.close()
    # 仅当前持有者可释放进程内闸门
    with _GATE_LOCK:
        if _GATE_HOLDERS.get(lock_key) == holder:
            _GATE_HOLDERS.pop(lock_key, None)
            gate = _GATES.get(lock_key)
            if gate is not None and gate.locked():
                gate.release()


@router.post("/acquire")
def api_acquire(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    key = (body.get("lock_key") or "").strip()
    if not key:
        raise HTTPException(400, "缺少 lock_key")
    acquire(key, user["username"], int(body.get("ttl_sec") or 20))
    return {"ok": True, "lock_key": key, "holder": user["username"]}


@router.post("/release")
def api_release(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    key = (body.get("lock_key") or "").strip()
    release(key, user["username"])
    return {"ok": True}
