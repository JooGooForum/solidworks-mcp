# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");

"""Disposable live regression for Sheet-metal workflow foundations."""

import os
from pathlib import Path

from solidworks_mcp import server  # noqa: F401 - registers every tool
from solidworks_mcp.sw_core import HANDLERS, as_list, byref_long, discover_template, running_app, value
from solidworks_mcp.sw_sheetmetal_workflows import PROFILE_ENV


def call(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    assert payload["ok"], payload
    return payload["data"]


def run():
    app = running_app()
    initial = {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    previous = os.environ.get(PROFILE_ENV)
    configured = str(app.GetUserPreferenceStringValue(1) or "")
    template = Path(configured) if configured else discover_template("part")
    assert template is not None
    template = Path(template)
    assert template.is_file(), template
    try:
        os.environ[PROFILE_ENV] = str(template)
        for mode in ("flat_blank", "finished_outer"):
            created = call("create_sheet_metal_plate", width_mm=100, height_mm=50,
                           thickness_mm=2, inside_radius_mm=1, dimension_mode=mode,
                           name=f"Plate_{mode}")
            assert created["snapshot"]["sheet_metal_body_count"] == 1, created
            verified = call("verify_sheet_metal_part", thickness_mm=2,
                            inside_radius_mm=1, expected_size_mm=[100, 50], tolerance_mm=.05)
            assert all(check["ok"] for check in verified["checks"]), verified
            inspected = call("inspect_sheet_metal_edit")
            assert len(inspected["edit_token"]) == 64, inspected
            app.CloseDoc(str(value(app.ActiveDoc, "GetTitle")))
        panel = call("create_sheet_metal_panel", width_mm=120, height_mm=60,
                     thickness_mm=1.5, inside_radius_mm=1.8,
                     dimension_mode="finished_outer", flange_sides=["left", "right"],
                     flange_height_mm=25, flange_angle_degrees=90,
                     name="SheetMetal_Panel")
        assert panel["snapshot"]["sheet_metal_body_count"] == 1, panel
        assert panel["sides"] == ["left", "right"], panel
        assert not panel["snapshot"]["problems"], panel
        assert sorted(panel["snapshot"]["bounding_box"]["size_mm"])[0] > 20, panel
        app.CloseDoc(str(value(app.ActiveDoc, "GetTitle")))
        print("sheet-metal profile workflow, both dimension modes, and verified two-flange geometry passed.", flush=True)
    finally:
        if previous is None:
            os.environ.pop(PROFILE_ENV, None)
        else:
            os.environ[PROFILE_ENV] = previous
        for title in [str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))]:
            if title not in initial:
                app.CloseDoc(title)
        if original:
            app.ActivateDoc3(original, False, 0, byref_long())
        assert {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))} == initial


if __name__ == "__main__":
    run()
