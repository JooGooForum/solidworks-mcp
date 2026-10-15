# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Sheet-metal live checks using scratch documents only, restoring the session."""

import uuid
try:
    from .live_expansion_regression import call, near, volume
except ImportError:  # direct script execution
    from live_expansion_regression import call, near, volume
from solidworks_mcp.sw_core import OUTPUT_ROOT, apply_transform, as_list, byref_long, running_app, value


def run():
    app = running_app()
    initial = {str(value(d, "GetTitle")) for d in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    try:
        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="Plate")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=50)
        call("close_sketch")
        call("sheet_metal_base_flange", sketch_name="Plate", thickness_mm=2, bend_radius_mm=1, k_factor=0.5)
        near(volume(), 10000, "flat sheet volume")
        definitions = call("list_sheet_metal_features")
        assert len(definitions["sheet_metal"]) == 1, definitions
        parameters = call("get_sheet_metal_parameters")["parameters"]
        near(parameters["thickness_mm"], 2, "sheet thickness")
        call("set_sheet_metal_parameters", thickness_mm=3, bend_radius_mm=2, k_factor=0.4)
        near(volume(), 15000, "updated sheet volume")
        parameters = call("get_sheet_metal_parameters")["parameters"]
        near(parameters["thickness_mm"], 3, "updated thickness")
        near(parameters["bend_radius_mm"], 2, "updated radius")
        near(parameters["k_factor"], 0.4, "updated K-factor")
        faces = call("list_faces")["faces"]
        sketch_face = max(faces, key=lambda item: item.get("area_mm2", 0))["index"]
        call("create_sketch", face_index=sketch_face, name="DXF_Bend_Line")
        sketch = app.ActiveDoc.SketchManager.ActiveSketch
        transform = list(value(value(sketch, "ModelToSketchTransform"), "ArrayData"))
        points = [apply_transform([coordinate / 1000 for coordinate in item["point_mm"]], transform)
                  for item in call("list_vertices")["vertices"]]
        xs, ys = [point[0] * 1000 for point in points], [point[1] * 1000 for point in points]
        middle_x = (min(xs) + max(xs)) / 2
        call("draw_line", x1_mm=middle_x, y1_mm=min(ys), x2_mm=middle_x, y2_mm=max(ys))
        call("close_sketch")
        call("sheet_metal_sketched_bend", sketch_name="DXF_Bend_Line", angle_degrees=90,
             use_default_radius=True, name="DXF_Test_Bend")
        call("set_flat_pattern", flat=True)
        assert all(not f["suppressed"] for f in call("list_sheet_metal_features")["flat_patterns"])
        assert volume() >= 14999, "flattening unexpectedly removed sheet-metal volume"
        call("set_flat_pattern", flat=False)
        assert all(f["suppressed"] for f in call("list_sheet_metal_features")["flat_patterns"])
        folder = OUTPUT_ROOT / ".sheetmetal-tests" / uuid.uuid4().hex
        call("save_document", path=str(folder / "plate.SLDPRT"))
        exported = call("export_flat_pattern", path=str(folder / "plate.dxf"))
        assert exported["entity_count"] > 0 and exported["bend_entity_count"] > 0, exported
        body_feature = call("list_sheet_metal_features")["sheet_metal"][0]["feature"]
        token = call("inspect_sheet_metal_edit")["edit_token"]
        call("set_sheet_metal_parameters", feature_name=body_feature, thickness_mm=4,
             bend_radius_mm=3, k_factor=0.3, edit_token=token)
        verified = call("verify_sheet_metal_part", thickness_mm=4, inside_radius_mm=3,
                        expected_body_count=1, minimum_volume_mm3=1)
        assert all(check["ok"] for check in verified["checks"]), verified
        print("Sheet-metal creation, guarded parameter edit, flatten/refold, DXF entities and bend lines verified.", flush=True)
    finally:
        for title in [str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))]:
            if title not in initial:
                app.CloseDoc(title)
        if original:
            app.ActivateDoc3(original, False, 0, byref_long())
        assert {str(value(d, "GetTitle")) for d in as_list(value(app, "GetDocuments"))} == initial


if __name__ == "__main__":
    run()
