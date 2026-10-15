# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0

"""Disposable live regressions for individual sheet-metal primitives."""

from solidworks_mcp import server  # noqa: F401
from solidworks_mcp.sw_core import HANDLERS, apply_transform, as_list, byref_long, require_part, running_app, value
from solidworks_mcp.sw_sheetmetal_workflows import _wall_face_for_flange


def call(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    assert payload["ok"], {"tool": tool_name, "payload": payload}
    return payload["data"]


def new_sheet(name):
    call("create_new_document", kind="part")
    call("create_sketch", plane="front", name=name)
    call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    call("close_sketch")
    call("sheet_metal_base_flange", sketch_name=name, thickness_mm=1.5,
         bend_radius_mm=1.8, k_factor=.5)


def top_long_edge():
    edges = call("list_edges", curve_type="line")["edges"]
    candidates = [edge for edge in edges if abs(edge.get("length_mm", 0) - 100) < .01]
    assert candidates, edges
    return max(candidates, key=lambda item: max((item.get("start_mm") or [0, 0, 0])[2],
                                                 (item.get("end_mm") or [0, 0, 0])[2]))["index"]


def largest_face():
    faces = call("list_faces")["faces"]
    return max(faces, key=lambda item: item.get("area_mm2", 0))["index"]


def run():
    app = running_app()
    initial = {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    try:
        new_sheet("HemBase")
        call("sheet_metal_hem", selection={"edges": [top_long_edge()]},
             hem_type="open", position="material_inside", length_mm=12,
             gap_mm=1, radius_mm=1.8, angle_degrees=180, name="MCP_Hem")
        call("create_sketch", plane="front", name="NormalCutProfile")
        call("draw_rectangle", x1_mm=30, y1_mm=20, x2_mm=50, y2_mm=40)
        call("close_sketch")
        cut = call("sheet_metal_normal_cut", sketch_name="NormalCutProfile",
                   end_condition="through_all", optimize_geometry=True, name="MCP_NormalCut")
        assert cut["normal_cut"] and cut["optimize_geometry"], cut
        call("set_sheet_metal_parameters", thickness_mm=2, bend_radius_mm=2.5, k_factor=.45)
        verified = call("verify_sheet_metal_part", thickness_mm=2, inside_radius_mm=2.5,
                        expected_body_count=1, minimum_volume_mm3=1)
        assert all(check["ok"] for check in verified["checks"]), verified
        assert not call("check_errors")["problems"]
        app.CloseDoc(str(value(app.ActiveDoc, "GetTitle")))

        new_sheet("BreakCornerBase")
        call("edge_flange", selection={"edges": [top_long_edge()]}, height_mm=20,
             angle_degrees=90, name="BreakCornerWall")
        _, doc = require_part()
        wall_face = _wall_face_for_flange(doc, "BreakCornerWall")
        broken = call("sheet_metal_break_corner", selection={"faces": [wall_face]},
                      corner_type="chamfer", size_mm=2, name="MCP_BreakCorner")
        assert broken["break_corner"]["entity_count"] >= 1, broken
        assert abs(broken["break_corner"]["distance_mm"] - 2) < .001, broken
        assert not call("check_errors")["problems"]
        app.CloseDoc(str(value(app.ActiveDoc, "GetTitle")))

        new_sheet("BendBase")
        call("create_sketch", face_index=largest_face(), name="BendLine")
        _, doc = require_part()
        sketch = doc.SketchManager.ActiveSketch
        model_to_sketch = list(value(value(sketch, "ModelToSketchTransform"), "ArrayData"))
        points = [apply_transform([coordinate / 1000 for coordinate in item["point_mm"]], model_to_sketch)
                  for item in call("list_vertices")["vertices"]]
        xs, ys = [point[0] * 1000 for point in points], [point[1] * 1000 for point in points]
        middle_x = (min(xs) + max(xs)) / 2
        call("draw_line", x1_mm=middle_x, y1_mm=min(ys), x2_mm=middle_x, y2_mm=max(ys))
        call("close_sketch")
        bend = call("sheet_metal_sketched_bend", sketch_name="BendLine",
                    angle_degrees=90, use_default_radius=True,
                    position="material_inside", name="MCP_SketchedBend")
        assert abs(bend["sketched_bend"]["angle_degrees"] - 90) < .001, bend
        assert not call("check_errors")["problems"]
        print("Hem, normal cut, parameter edit, break corner, and sketched bend passed.", flush=True)
    finally:
        for title in [str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))]:
            if title not in initial:
                app.CloseDoc(title)
        if original:
            app.ActivateDoc3(original, False, 0, byref_long())
        remaining = {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))}
        assert remaining == initial, {"before": sorted(initial), "after": sorted(remaining)}


if __name__ == "__main__":
    run()
