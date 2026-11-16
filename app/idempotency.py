"""Optional replay keys backed by existing durable resource IDs; no schema change."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import text


def replay(db, model, request_id, owner_id, expected):
    if request_id is None:
        return None
    if db.bind.dialect.name == "postgresql":
        # Separate namespace from queue/migration/budget locks; bounded lock wait.
        key = int.from_bytes(
            hashlib.sha256(f"create:{model.__tablename__}:{request_id}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    record = db.get(model, request_id)
    if record is not None and record.owner_id != owner_id:
        raise HTTPException(404, "Resource not found")
    if record is not None and any(getattr(record, field) != value for field, value in expected.items()):
        raise HTTPException(409, "Request key already used; start a new request for different content")
    return record


def resource_id(request_id):
    return {"id": request_id} if request_id is not None else {}
