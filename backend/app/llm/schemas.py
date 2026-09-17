"""JSON schemas for structured outputs, and the Pydantic models that validate what comes back.

Structured outputs accept a limited JSON-Schema subset: no recursion, no numeric or string
constraints, ``additionalProperties: false`` on every object. Length rules (≤ 5 word titles and so
on) are therefore enforced in :mod:`app.pipeline.grounding` rather than in the schema.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

NODE_KINDS = ("start", "process", "decision", "datastore", "external", "output")
EDGE_KINDS = ("data", "control", "error")

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["summaries"],
    "additionalProperties": False,
}

FLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short unique id inside this answer"},
                    "kind": {"type": "string", "enum": list(NODE_KINDS)},
                    "title": {"type": "string", "description": "Verb phrase, at most 5 words"},
                    "explanation": {
                        "type": "string",
                        "description": "At most 25 simple words: what happens and why",
                    },
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "outputs": {"type": "array", "items": {"type": "string"}},
                    "covers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids copied from the list you were given. Empty for steps.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "For steps only: first line of this step, else 0",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "For steps only: last line of this step, else 0",
                    },
                },
                "required": [
                    "key",
                    "kind",
                    "title",
                    "explanation",
                    "inputs",
                    "outputs",
                    "covers",
                    "start_line",
                    "end_line",
                ],
                "additionalProperties": False,
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "label": {
                        "type": "string",
                        "description": "The data that moves, at most 6 words",
                    },
                    "data_shape": {"type": "string"},
                    "kind": {"type": "string", "enum": list(EDGE_KINDS)},
                },
                "required": ["source", "target", "label", "data_shape", "kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["nodes", "edges"],
    "additionalProperties": False,
}


class SummaryItem(BaseModel):
    id: str
    summary: str


class SummaryResponse(BaseModel):
    summaries: list[SummaryItem] = Field(default_factory=list)


class LlmNode(BaseModel):
    key: str
    kind: Literal["start", "process", "decision", "datastore", "external", "output"]
    title: str
    explanation: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


class LlmEdge(BaseModel):
    source: str
    target: str
    label: str = ""
    data_shape: str = ""
    kind: Literal["data", "control", "error"] = "data"


class FlowResponse(BaseModel):
    nodes: list[LlmNode] = Field(default_factory=list)
    edges: list[LlmEdge] = Field(default_factory=list)
