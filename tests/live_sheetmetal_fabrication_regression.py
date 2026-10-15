# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");

"""Native edge-flange and selective unfold/fold regression on a scratch part."""

from solidworks_mcp import server  # noqa: F401
from solidworks_mcp.sw_core import HANDLERS, apply_transform, as_list, byref_long, running_app, value
from solidworks_mcp.sw_core import feature_property, require_part
from solidworks_mcp.sw_sheetmetal import _all_feature_objects


def call(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    assert payload["ok"], payload
    return payload["data"]


def run():
    app = running_app()
    initial = {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    try:
        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="Panel")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=50)
        call("close_sketch")
        call("sheet_metal_base_flange", sketch_name="Panel", thickness_mm=2,
             bend_radius_mm=1, k_factor=.5)
        before_box = sorted(call("get_bounding_box")["size_mm"])
        before_volume = call("get_mass_properties")["volume_mm3"]
        edges = call("list_edges", curve_type="line")["edges"]
        long_edges = [edge for edge in edges if abs(edge.get("length_mm", 0) - 100) < .01]
        assert long_edges, edges
        edge = max(long_edges, key=lambda item: max((item.get("start_mm") or [0, 0, 0])[2],
                                                     (item.get("end_mm") or [0, 0, 0])[2]))
        call("edge_flange", selection={"edges": [edge["index"]]}, height_mm=20,
             angle_degrees=90, corner_gap_mm=.5, name="TrayWall")
        after_box = sorted(call("get_bounding_box")["size_mm"])
        after_volume = call("get_mass_properties")["volume_mm3"]
        assert after_box[0] > before_box[0] + 10, {"before": before_box, "after": after_box}
        assert after_volume > before_volume + 1000, {"before": before_volume, "after": after_volume}
        assert not call("check_errors")["problems"]
        app.CloseDoc(str(value(app.ActiveDoc, "GetTitle")))

        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="BendPanel")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=50)
        call("close_sketch")
        call("sheet_metal_base_flange", sketch_name="BendPanel", thickness_mm=2,
             bend_radius_mm=1, k_factor=.5)
        faces = call("list_faces")["faces"]
        sketch_face = max(faces, key=lambda item: item.get("area_mm2", 0))["index"]
        call("create_sketch", face_index=sketch_face, name="SelectiveBendLine")
        sketch = app.ActiveDoc.SketchManager.ActiveSketch
        transform = list(value(value(sketch, "ModelToSketchTransform"), "ArrayData"))
        points = [apply_transform([coordinate / 1000 for coordinate in item["point_mm"]], transform)
                  for item in call("list_vertices")["vertices"]]
        xs, ys = [point[0] * 1000 for point in points], [point[1] * 1000 for point in points]
        middle_x = (min(xs) + max(xs)) / 2
        call("draw_line", x1_mm=middle_x, y1_mm=min(ys), x2_mm=middle_x, y2_mm=max(ys))
        call("close_sketch")
        call("sheet_metal_sketched_bend", sketch_name="SelectiveBendLine", angle_degrees=90,
             use_default_radius=True, name="SelectiveBend")
        sheet_metal = call("list_sheet_metal_features")
        bends = [item["feature"] for item in sheet_metal["bends"]]
        _, active = require_part()
        tree = [(str(value(item, "Name")), str(feature_property(item, "GetTypeName2", "")))
                for item in _all_feature_objects(active)]
        assert bends, {"sheet_metal": sheet_metal, "recursive_tree": tree}
        faces = call("list_faces")["faces"]
        fixed = max(faces, key=lambda item: item.get("area_mm2", 0))["index"]
        unfolded = call("sheet_metal_unfold", fixed_face_index=fixed,
                        bend_feature_names=bends, name="MCP_Unfold")
        assert unfolded["fold_data"]["bend_count"] == len(bends), unfolded
        folded = call("sheet_metal_fold", fixed_face_index=fixed,
                      bend_feature_names=bends, unfold_feature_name="MCP_Unfold", name="MCP_Fold")
        assert folded["fold_data"]["bend_count"] == len(bends), folded
        assert not call("check_errors")["problems"]
        print("Edge flange and selective native unfold/fold passed with definition readback.", flush=True)
    finally:
        for title in [str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))]:
            if title not in initial:
                app.CloseDoc(title)
        if original:
            app.ActivateDoc3(original, False, 0, byref_long())
        assert {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))} == initial


if __name__ == "__main__":
    run()
