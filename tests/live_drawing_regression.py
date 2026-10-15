# Copyright 2026 JIALE LIU
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Live regression for drawing-template preservation and targeted auto-dimensioning.

Set both variables before running this test against an existing SOLIDWORKS
session. The test creates only disposable unsaved drawings and closes them:

    SW_MCP_LIVE_DRAWING_TEMPLATE
    SW_MCP_LIVE_MODEL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp.sw_core import running_app, value
from solidworks_mcp.sw_drawing import (
    auto_dimension_view,
    create_drawing,
    insert_model_view,
    list_drawing_views,
)
from solidworks_mcp.sw_manage import activate_document, close_document


def require(payload: dict[str, Any], context: str) -> dict[str, Any]:
    if not payload.get("ok"):
        raise AssertionError(f"{context} failed: {payload.get('message')}")
    return payload["data"]


def required_path(variable: str) -> str:
    path = os.environ.get(variable, "")
    if not path:
        raise RuntimeError(f"Set {variable} to an explicit local path.")
    return path


def active_title(app: Any) -> str:
    return str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""


def close_active_disposable(app: Any) -> None:
    title = active_title(app)
    if title:
        require(close_document({"name": title, "discard_changes": True}), f"close {title}")


def view_counts() -> dict[str, int]:
    data = require(list_drawing_views({}), "list drawing views")
    return {str(view["name"]): int(view.get("dimensions", 0)) for view in data["views"]}


def main() -> None:
    template = required_path("SW_MCP_LIVE_DRAWING_TEMPLATE")
    model = required_path("SW_MCP_LIVE_MODEL")
    app = running_app()
    original = active_title(app)
    try:
        baseline = require(create_drawing({"template_path": template}), "create baseline drawing")
        expected_format = str(baseline.get("sheet_format_path") or "")
        expected_sheets = [sheet["name"] for sheet in baseline["sheets"]]
        if not expected_format:
            raise AssertionError("Template drawing did not report an inherited sheet-format path.")
        close_active_disposable(app)

        changed_projection = not bool(baseline["first_angle"])
        drawing = require(
            create_drawing({"template_path": template, "first_angle": changed_projection}),
            "create drawing with projection override",
        )
        actual_format = str(drawing.get("sheet_format_path") or "")
        if actual_format.casefold() != expected_format.casefold():
            raise AssertionError(f"Sheet format changed: {expected_format!r} -> {actual_format!r}")
        if [sheet["name"] for sheet in drawing["sheets"]] != expected_sheets:
            raise AssertionError(f"Template sheets changed: {drawing['sheets']}")

        front = require(
            insert_model_view({"model_path": model, "view": "front", "x_mm": 90, "y_mm": 180}),
            "insert front view",
        )["view"]["name"]
        iso = require(
            insert_model_view({"model_path": model, "view": "isometric", "x_mm": 260, "y_mm": 120}),
            "insert isometric view",
        )["view"]["name"]
        before = view_counts()
        outcome = require(auto_dimension_view({"view_name": front}), "auto-dimension front view")
        after = view_counts()
        if outcome.get("view_name") != front or after.get(front, 0) <= before.get(front, 0):
            raise AssertionError(f"Requested view was not dimensioned: {outcome}")
        if after.get(iso, 0) != before.get(iso, 0):
            raise AssertionError(f"Unrequested view was dimensioned: {before} -> {after}")
        print("Drawing workflow live regression passed.")
    finally:
        current = active_title(app)
        if current and current != original:
            outcome = close_document({"name": current, "discard_changes": True})
            if not outcome.get("ok"):
                print(f"WARNING: could not close disposable drawing {current}: {outcome.get('message')}")
        if original:
            outcome = activate_document({"name": original})
            if not outcome.get("ok"):
                print(f"WARNING: could not restore original active document {original}.")


if __name__ == "__main__":
    main()
