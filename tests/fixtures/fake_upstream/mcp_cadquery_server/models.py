"""Fake of upstream ``models.py``: only what the shim reads."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ExecuteCadqueryScriptArgs(BaseModel):
    workspace_path: str = Field(...)
    script: str = Field(...)
    parameter_sets: Optional[list[dict[str, Any]]] = Field(default=None)
    parameters: Optional[dict[str, Any]] = Field(default=None)
