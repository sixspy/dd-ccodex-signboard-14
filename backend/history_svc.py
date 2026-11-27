"""变更历史。"""
from __future__ import annotations

from fastapi import APIRouter, Header

from auth import current_user
from db import connect, rows_to_list

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(limit: int = 100, authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                "SELECT * FROM change_history ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 300)),),
            ).fetchall()
        )
    return {"items": rows}


@router.get("/rejections")
def list_rejections(authorization: str | None = Header(default=None)):
    """signboard-14：星期不匹配拒播痕专册，便于核对空播有据。"""
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                "SELECT * FROM change_history WHERE action='reject_weekday' ORDER BY id DESC"
            ).fetchall()
        )
    return {"items": rows}
