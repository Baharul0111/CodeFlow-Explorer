"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.pipeline.scan import EntryHint, LanguageStat, SkippedFile


class ScanSummary(BaseModel):
    languages: dict[str, LanguageStat]
    file_count: int
    code_file_count: int
    function_count: int | None = None
    class_count: int | None = None
    skipped_counts: dict[str, int]
    skipped_examples: list[SkippedFile]
    frameworks: list[str]
    entry_hints: list[EntryHint]
    readme_excerpt: str


class ProjectOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    upload_bytes: int
    status: str
    model_id: str | None
    deep_model_id: str | None
    scan: ScanSummary | None
    estimate: dict[str, Any] | None
    error: str | None


class ProjectListItem(BaseModel):
    id: str
    name: str
    created_at: datetime
    status: str
    model_id: str | None
    file_count: int
    node_count: int
    total_cost_usd: float


NodeKind = Literal["start", "process", "decision", "datastore", "external", "output"]
NodeStatus = Literal["pending", "generating", "ready", "error"]
EdgeKind = Literal["data", "control", "error"]


class CodeRef(BaseModel):
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str = ""


class NodeOut(BaseModel):
    id: str
    parent_id: str | None
    level: int
    kind: NodeKind
    title: str
    explanation: str
    inputs: list[str]
    outputs: list[str]
    code_refs: list[CodeRef]
    has_children: bool
    status: NodeStatus
    scope: str
    error: str | None = None


class EdgeOut(BaseModel):
    id: str
    parent_id: str | None
    source: str
    target: str
    label: str
    data_shape: str
    kind: EdgeKind
