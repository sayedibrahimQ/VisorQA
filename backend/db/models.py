"""Single watched repository persistence (Task 1).

VisorQA watches exactly ONE repository. The singleton record lives in the
``watched_repository`` SQLModel table (id = 1); when PostgreSQL is offline
locally it falls back to a JSON file (``artifacts/watched_repo.json``, or
``$VISORQA_WATCHED_REPO_JSON``) so the choice survives restarts either way.
Nothing here fabricates a repository: no record means "not selected yet".
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WatchedRepository(SQLModel, table=True):
    """Singleton row (id = 1): the one repository VisorQA monitors."""

    __tablename__ = "watched_repository"

    id: int = Field(default=1, primary_key=True)
    repo_full_name: str = Field(index=True)  # e.g. "sayedibrahimQ/visorqa-demo-storefront"
    default_branch: str = Field(default="main")
    installation_id: Optional[int] = Field(default=None)
    webhook_active: bool = Field(default=False)
    auto_heal_enabled: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=_utc_now)


def fallback_path() -> Path:
    override = (os.environ.get("VISORQA_WATCHED_REPO_JSON") or "").strip()
    if override:
        return Path(override)
    try:
        from backend.core.artifacts import artifacts_root
        return artifacts_root() / "watched_repo.json"
    except Exception:
        return Path("artifacts") / "watched_repo.json"


def _serialize(record: Any) -> Dict[str, Any]:
    if isinstance(record, dict):
        data = dict(record)
    else:
        data = {
            "id": record.id,
            "repo_full_name": record.repo_full_name,
            "default_branch": record.default_branch,
            "installation_id": record.installation_id,
            "webhook_active": bool(record.webhook_active),
            "auto_heal_enabled": bool(record.auto_heal_enabled),
            "updated_at": record.updated_at,
        }
    updated = data.get("updated_at")
    if isinstance(updated, datetime):
        data["updated_at"] = updated.isoformat()
    data["id"] = int(data.get("id") or 1)
    data.setdefault("default_branch", "main")
    data["webhook_active"] = bool(data.get("webhook_active"))
    data["auto_heal_enabled"] = bool(data.get("auto_heal_enabled", True))
    return data


def _db_load() -> Optional[Dict[str, Any]]:
    from sqlmodel import Session

    from backend.db.repository import engine

    WatchedRepository.__table__.create(engine, checkfirst=True)
    with Session(engine) as session:
        row = session.get(WatchedRepository, 1)
        return _serialize(row) if row is not None else None


def _db_save(record: Dict[str, Any]) -> Dict[str, Any]:
    from sqlmodel import Session

    from backend.db.repository import engine

    WatchedRepository.__table__.create(engine, checkfirst=True)
    with Session(engine) as session:
        row = session.get(WatchedRepository, 1)
        if row is None:
            row = WatchedRepository(id=1, repo_full_name=record["repo_full_name"])
        row.repo_full_name = record["repo_full_name"]
        row.default_branch = record.get("default_branch") or "main"
        row.installation_id = record.get("installation_id")
        row.webhook_active = bool(record.get("webhook_active"))
        row.auto_heal_enabled = bool(record.get("auto_heal_enabled", True))
        row.updated_at = _utc_now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize(row)


def _file_load() -> Optional[Dict[str, Any]]:
    path = fallback_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not str(data.get("repo_full_name") or "").strip():
        return None
    return _serialize(data)


def _file_save(record: Dict[str, Any]) -> Dict[str, Any]:
    path = fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    tmp.replace(path)
    return record


def get_watched_repository() -> Optional[Dict[str, Any]]:
    """Persisted watched repo, or None when none has been selected yet."""
    override = (os.environ.get("VISORQA_WATCHED_REPO_JSON") or "").strip()
    if override:
        return _file_load()
    try:
        record = _db_load()
        if record is not None:
            return record
    except Exception:
        pass  # PostgreSQL offline locally -> JSON fallback below.
    return _file_load()


def save_watched_repository(
    repo_full_name: str,
    default_branch: str = "main",
    installation_id: Optional[int] = None,
    webhook_active: bool = False,
    auto_heal_enabled: bool = True,
) -> Dict[str, Any]:
    """Upsert the singleton watched-repository record (DB, else JSON file)."""
    record: Dict[str, Any] = {
        "id": 1,
        "repo_full_name": repo_full_name.strip(),
        "default_branch": default_branch or "main",
        "installation_id": installation_id,
        "webhook_active": bool(webhook_active),
        "auto_heal_enabled": bool(auto_heal_enabled),
        "updated_at": _utc_now().isoformat(),
    }
    override = (os.environ.get("VISORQA_WATCHED_REPO_JSON") or "").strip()
    if override:
        return _file_save(record)
    try:
        saved = _db_save(record)
        try:
            _file_save(record)
        except Exception:
            pass
        return saved
    except Exception:
        return _file_save(record)
