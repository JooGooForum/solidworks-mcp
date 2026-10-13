# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Live check of the five tools that issue #3 reported as unusable.

`draw_spline` (sw_sketch), `list_mates` (sw_assembly) and `set_drawing_view` /
`insert_section_view` / `insert_detail_view` (sw_drawing) each import `sw_core`
from inside the function body.  Commit 10c2beb made those imports relative;
this script drives every one of them on a live session so the fix is proven by
behaviour instead of by the import line alone.
"""

import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_expansion_regression import call, near
from solidworks_mcp.sw_core import OUTPUT_ROOT, as_list, running_app, value


def main():
    app = running_app()
    initial = {str(value(document, "GetTitle")) for document in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    folder = OUTPUT_ROOT / ".reported-tools" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        thick = folder / "Thick.SLDPRT"
        thin = folder / "Thin.SLDPRT"
        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="Base")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=30)
        call("close_sketch")
        call("boss_extrude", sketch_name="Base", depth_mm=10)
        near(call("get_mass_properties")["volume_mm3"], 12000, "thick fixture volume")
        call("create_sketch", plane="front", name="Curve")
        spline = call("draw_spline", points=[{"x_mm": 5, "y_mm": 5}, {"x_mm": 20, "y_mm": 25},
                                             {"x_mm": 35, "y_mm": 5}])
        segments = call("list_sketch_segments", sketch_name="Curve")["segments"]
        assert spline["segments_added"] >= 1, spline
        assert len(segments) == 1 and segments[0]["type"] == "spline", segments
        call("close_sketch")
        call("save_document", path=str(thick))
        call("close_document", name=call("list_open_documents")["active_title"], discard_changes=True)
        print("draw_spline added a real spline segment and the part saved.", flush=True)

        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="Base")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=25, y2_mm=20)
        call("close_sketch")
        call("boss_extrude", sketch_name="Base", depth_mm=15)
        near(call("get_mass_properties")["volume_mm3"], 7500, "thin fixture volume")
        call("save_document", path=str(thin))
        call("close_document", name=call("list_open_documents")["active_title"], discard_changes=True)

        assembly = call("create_new_document", kind="assembly")["document"]["title"]
        first = call("insert_component", path=str(thick))["component"]
        call("set_component_fixed", component_names=[first], fixed=False)
        second = call("insert_component", path=str(thin))["component"]
        call("set_component_fixed", component_names=[second], fixed=False)
        faces = call("list_faces")["faces"]
        thick_face = next(entry for entry in faces if abs(entry["area_mm2"] - 1200) < 0.5)
        thin_face = next(entry for entry in faces if abs(entry["area_mm2"] - 500) < 0.5)
        mate = call("add_mate", mate_type="coincident", selection={"faces": [thick_face["index"], thin_face["index"]]})
        listed = call("list_mates")
        mates = listed.get("mates") or listed.get("features") or []
        assert mates and all(entry["name"] for entry in mates), listed
        print(f"list_mates read {len(mates)} mate(s) after add_mate: "
              f"{json.dumps([entry['name'] for entry in mates], ensure_ascii=False)}", flush=True)
        print(f"Mate type readback: {json.dumps(mate, ensure_ascii=False)[:300]}", flush=True)
        call("close_document", name=assembly, discard_changes=True)

        drawing = call("create_new_document", kind="drawing")["document"]["title"]
        placed = call("insert_model_view", model_path=str(thick), view="front", x_mm=120, y_mm=130, scale=0.5)
        views = call("list_drawing_views")["views"]
        name = placed["view"]["name"]
        assert any(view["name"] == name for view in views), views
        moved = call("set_drawing_view", name=name, x_mm=130, y_mm=120, scale=0.4,
                     display_mode="shaded_with_edges", tangent_edges="visible")
        entry = moved["view"]
        near(entry["position_mm"][0], 130, "moved view x")
        near(entry["position_mm"][1], 120, "moved view y")
        near(entry["scale"], 0.4, "moved view scale")
        print(f"set_drawing_view read back {json.dumps(entry, ensure_ascii=False)}", flush=True)

        section = call("insert_section_view", parent_view=name, x1_mm=130, y1_mm=112, x2_mm=130, y2_mm=128,
                       place_x_mm=175, place_y_mm=120, label="A")
        assert section["parent"] == name, section
        detail = call("insert_detail_view", parent_view=name, center_x_mm=134, center_y_mm=122, radius_mm=4,
                      place_x_mm=175, place_y_mm=85, label="I", scale_numerator=1, scale_denominator=2)
        assert detail["parent"] == name, detail
        after = call("list_drawing_views")["views"]
        assert len(after) == len(views) + 2, after
        print(f"Drawing views after the section and detail: "
              f"{json.dumps([view['name'] for view in after], ensure_ascii=False)}", flush=True)
        call("close_document", name=drawing, discard_changes=True)
    finally:
        for _ in range(2):
            documents = list(call("list_open_documents")["documents"])
            documents.sort(key=lambda entry: entry["document_type"] != "assembly")
            for document in documents:
                if document["title"] not in initial:
                    try:
                        call("close_document", name=document["title"], discard_changes=True)
                    except Exception:
                        pass
        remaining = [entry["title"] for entry in call("list_open_documents")["documents"]]
        if original and original in remaining:
            call("activate_document", name=original)
        print("REMAINING " + json.dumps(remaining, ensure_ascii=False), flush=True)
        assert set(remaining) <= initial, remaining


if __name__ == "__main__":
    main()
