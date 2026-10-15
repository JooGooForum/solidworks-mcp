# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0

"""Disposable live regression for guarded sketch-to-model collinearity."""

from solidworks_mcp import server  # noqa: F401
from solidworks_mcp.sw_core import HANDLERS, as_list, byref_long, running_app, value


def call(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    assert payload["ok"], {"tool": tool_name, "payload": payload}
    return payload["data"]


def run():
    app = running_app()
    initial = {str(value(doc, "GetTitle")) for doc in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    try:
        call("create_new_document", kind="part")
        call("create_sketch", plane="front", name="AlignmentBase")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
        call("close_sketch")
        call("sheet_metal_base_flange", sketch_name="AlignmentBase", thickness_mm=1.5,
             bend_radius_mm=1.8, k_factor=.5)
        face = max(call("list_faces")["faces"], key=lambda item: item.get("area_mm2", 0))["index"]
        call("create_sketch", face_index=face, name="AlignmentLine")
        call("draw_line", x1_mm=20, y1_mm=10, x2_mm=80, y2_mm=10)
        call("close_sketch")

        inspected = call("inspect_sketch_alignment", sketch_name="AlignmentLine")
        pairs = inspected["compatible_pairs"]
        assert pairs, inspected
        pair = min(pairs, key=lambda item: item["gap_mm"])
        assert pair["gap_mm"] > .01, pair
        applied = call(
            "set_sketch_line_collinear_to_edge",
            sketch_name="AlignmentLine",
            sketch_segment_index=pair["sketch_segment_index"],
            edge_index=pair["edge_index"],
            sketch_segment_reference=pair["sketch_segment_reference"],
            model_edge_reference=pair["model_edge_reference"],
            edit_token=inspected["edit_token"],
        )
        assert applied["relations_added"] > 0 and applied["references_stable"], applied
        reread = call("inspect_sketch_alignment", sketch_name="AlignmentLine")
        final = next(item for item in reread["compatible_pairs"]
                     if item["sketch_segment_reference"] == pair["sketch_segment_reference"]
                     and item["model_edge_reference"] == pair["model_edge_reference"])
        assert final["gap_mm"] <= .001, final
        assert not call("check_errors")["problems"]
        print("Guarded direct collinear relation, persistent references, rollback restoration, and geometry readback passed.", flush=True)
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
