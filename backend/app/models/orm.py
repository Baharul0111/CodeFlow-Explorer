"""ORM tables.

Graph nodes and edges are stored per project. ``coverage`` on a node is the list of static unit ids
(``path/file.py::Class.method``) it covers — the grounding vocabulary used when expanding it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    upload_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    scan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    codemap_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deep_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estimate: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cost_limit_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(project_fk(), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # analysis | expand
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    current_item: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class FlowNode(Base):
    __tablename__ = "nodes"
    __table_args__ = (Index("ix_nodes_project_parent", "project_id", "parent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(project_fk(), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text, default="")
    inputs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    outputs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    code_refs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    coverage: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # system | stage | group | file | function | step
    scope: Mapped[str] = mapped_column(String(16), default="group")
    has_children: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FlowEdge(Base):
    __tablename__ = "edges"
    __table_args__ = (Index("ix_edges_project_parent", "project_id", "parent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(project_fk(), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128), default="")
    data_shape: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(16), default="data")


class LlmCache(Base):
    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(project_fk(), index=True)
    task: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKeyRecord(Base):
    """Encrypted-at-rest key for sessions that ticked "remember key on this server"."""

    __tablename__ = "api_keys"

    session_token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
