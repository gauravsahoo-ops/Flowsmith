"""Workflow Intermediate Representation (IR).

A clean, declarative intermediate representation of an automation pipeline
that abstracts business steps before compilation into Flowsmith DAG JSON.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class IRTrigger(BaseModel):
    id: str = "trigger_0"
    kind: str = "manual"
    system: str = "system"
    event: str = "trigger"
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_trigger(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            t = d.pop("type", None)
            if t:
                d.setdefault("kind", t)
                d.setdefault("system", t)
            params = d.pop("parameters", None)
            if params and isinstance(params, dict):
                d.setdefault("config", params)
            return d
        return data


class IRStep(BaseModel):
    id: str
    name: str
    kind: str = "action"
    system: Optional[str] = None
    operation: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    retry: int = 0
    timeout_seconds: int = 300
    description: str = ""
    target_handle: str = "main"

    @model_validator(mode="before")
    @classmethod
    def _normalize_step(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            t = d.pop("type", None)
            if t:
                d.setdefault("system", t)
                if t in ("if_condition", "condition"):
                    d.setdefault("kind", "condition")
                elif t in ("loop", "while", "for_each"):
                    d.setdefault("kind", "loop")
                elif t in ("parallel", "fork"):
                    d.setdefault("kind", "parallel")
                elif t in ("merge", "join"):
                    d.setdefault("kind", "merge")
                elif t in ("human_approval", "approval"):
                    d.setdefault("kind", "approval")
                elif t in ("ai_agent", "ai_completion"):
                    d.setdefault("kind", "ai_task")
                elif t in ("http_request", "http"):
                    d.setdefault("kind", "http")
                else:
                    d.setdefault("kind", "connector")
            params = d.pop("parameters", None)
            if params and isinstance(params, dict):
                d.setdefault("inputs", params)
                if "operation" in params and not d.get("operation"):
                    d["operation"] = params["operation"]
            return d
        return data


class IRConnection(BaseModel):
    source: str
    target: str
    source_handle: str = "main"
    target_handle: str = "main"

    @model_validator(mode="before")
    @classmethod
    def _normalize_conn(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "from_step" in d and "source" not in d:
                d["source"] = d.pop("from_step")
            elif "from" in d and "source" not in d:
                d["source"] = d.pop("from")
            if "to_step" in d and "target" not in d:
                d["target"] = d.pop("to_step")
            elif "to" in d and "target" not in d:
                d["target"] = d.pop("to")
            return d
        return data


class IRErrorPolicy(BaseModel):
    max_retries: int = 0
    backoff_strategy: str = "exponential"
    notify_on_failure: bool = False
    alert_channel: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_policy(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "backoff" in d and "backoff_strategy" not in d:
                d["backoff_strategy"] = d.pop("backoff")
            if "retry_attempts" in d and "max_retries" not in d:
                d["max_retries"] = d.pop("retry_attempts")
            return d
        return data


class WorkflowIR(BaseModel):
    """The complete Intermediate Representation of an automation workflow."""

    id: str = "ir_workflow"
    name: str = "Automation Workflow"
    description: str = ""
    trigger: IRTrigger = Field(default_factory=IRTrigger)
    steps: list[IRStep] = Field(default_factory=list)
    connections: list[IRConnection] = Field(default_factory=list)
    error_policy: IRErrorPolicy = Field(default_factory=IRErrorPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)

