# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Native sheet metal creation, parameters, flattening and DXF export."""

from pathlib import Path
import math
import uuid

from . import sw_feature
from .sw_core import (
    SELECTION_SCHEMA, apply_selection, apply_transform, as_list, clear_selection, dispatch_array, empty_variant, extension, feature_manager, feature_property,
    feature_result, find_feature, flag_methods, get_bodies, iter_feature_objects,
    iter_edge_objects, nothing, persistent_reference_id, rebuild, rename_feature, require_part, result,
    safe, select_sketch_for_feature, selectable, to_m, to_mm, tool, value, whats_wrong,
)
from .sw_file import validated_output_path
from .sw_multibody import _positive

EDIT_TOKEN = {"edit_token": {"type": "string", "description":
    "Fresh token from inspect_sheet_metal_edit; required when the active part already has a saved path."}}


def _guard_saved_document_edit(doc, args):
    """Require a fresh sheet-metal inspection token before mutating a saved part."""
    try:
        saved = bool(str(value(doc, "GetPathName") or ""))
    except Exception:
        saved = False
    if saved:
        from .sw_sheetmetal_workflows import require_edit_token
        require_edit_token(args.get("edit_token"))


def _sheet_features(doc):
    return [f for f in iter_feature_objects(doc) if str(feature_property(f, "GetTypeName2", "")) == "SheetMetal"]


def _flat_features(doc):
    return [f for f in iter_feature_objects(doc) if str(feature_property(f, "GetTypeName2", "")) == "FlatPattern"]


def _all_feature_objects(doc):
    seen = set()
    pending = list(iter_feature_objects(doc))
    while pending:
        feature = pending.pop(0)
        key = persistent_reference_id(doc, feature) if feature is not None else b""
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        yield feature
        child = safe(feature, "GetFirstSubFeature")
        sibling_names = set()
        while child is not None:
            name = str(feature_property(child, "Name", ""))
            if name in sibling_names:
                break
            sibling_names.add(name)
            pending.append(child)
            child = safe(child, "GetNextSubFeature")


def _suppressed(feature):
    flags = as_list(flag_methods(feature, "IsSuppressed2").IsSuppressed2(1, empty_variant()))
    if len(flags) != 1:
        raise RuntimeError("Could not read feature suppression in the current configuration.")
    return bool(flags[0])


def _read_parameters(feature):
    definition = value(feature, "GetDefinition")
    payload = {"feature": str(value(feature, "Name")), "thickness_mm": to_mm(float(value(definition, "Thickness"))),
               "bend_radius_mm": to_mm(float(value(definition, "BendRadius"))), "k_factor": float(value(definition, "KFactor"))}
    for member, key in (("UseGaugeTable", "use_gauge_table"), ("UseMaterialSheetMetalParameters", "use_material_sheet_metal_parameters"),
                        ("UseDefaultBendAllowance", "use_default_bend_allowance"),
                        ("OverrideDefaultSheetMetalParameters", "override_document_defaults")):
        try:
            payload[key] = bool(value(definition, member))
        except Exception:
            pass
    for member, key in (("GaugeTablePath", "gauge_table_path"), ("ThicknessTableName", "gauge_table_thickness")):
        try:
            payload[key] = str(value(definition, member) or "")
        except Exception:
            pass
    payload["allowance_source"] = "document_default" if payload.get("use_default_bend_allowance") else "feature_override"
    return payload


@tool("sheet_metal_base_flange", "Create a native sheet-metal base flange from a closed or open sketch. Set use_document_defaults to preserve the template/material sheet-metal parameters and gauge table. Otherwise thickness, radius and K-factor are explicit.",
      {**EDIT_TOKEN, "sketch_name": {"type": "string"}, "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
       "bend_radius_mm": {"type": "number", "minimum": 0, "default": 1}, "depth_mm": {"type": "number", "exclusiveMinimum": 0, "default": 50},
       "k_factor": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
       "use_document_defaults": {"type": "boolean", "default": False},
       "reverse_thickness": {"type": "boolean", "default": False}, "reverse": {"type": "boolean", "default": False}, "name": {"type": "string"}})
def sheet_metal_base_flange(args):
    depth = _positive(args.get("depth_mm", 50), "depth_mm")
    use_defaults = bool(args.get("use_document_defaults", False))
    explicit = [key for key in ("thickness_mm", "bend_radius_mm", "k_factor") if key in args]
    if use_defaults and explicit:
        raise RuntimeError("use_document_defaults cannot be combined with thickness_mm, bend_radius_mm or k_factor.")
    if not use_defaults:
        if "thickness_mm" not in args:
            raise RuntimeError("thickness_mm is required unless use_document_defaults is true.")
        thickness = _positive(args["thickness_mm"], "thickness_mm")
        radius = float(args.get("bend_radius_mm", 1))
        factor = float(args.get("k_factor", 0.5))
        if not math.isfinite(radius) or radius < 0 or not math.isfinite(factor) or not 0 <= factor <= 1:
            raise RuntimeError("Radius must be finite and nonnegative; K-factor must be between 0 and 1.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    if use_defaults:
        manager = flag_methods(feature_manager(doc), "CreateDefinition", "CreateFeature")
        definition = flag_methods(manager.CreateDefinition(34), "Initialize")  # swFmBaseFlange
        definition.Initialize(True, False, nothing(), False, 0, False, 0.0, 0.0, 0.0)
        definition.D1OffsetType = 1
        definition.D2OffsetType = 1
        definition.D1OffsetDistance = to_m(depth)
        definition.D2OffsetDistance = to_m(depth)
        definition.ReverseThickness = bool(args.get("reverse_thickness", False))
        definition.ReverseDirection = bool(args.get("reverse", False))
        feature = manager.CreateFeature(definition)
    else:
        manager = flag_methods(feature_manager(doc), "CreateCustomBendAllowance", "InsertSheetMetalBaseFlange2")
        allowance = manager.CreateCustomBendAllowance()
        allowance.Type = 2
        allowance.KFactor = factor
        feature = manager.InsertSheetMetalBaseFlange2(to_m(thickness), bool(args.get("reverse_thickness", False)), to_m(radius),
            to_m(depth), to_m(depth), bool(args.get("reverse", False)), 0, 0, 1, allowance,
            False, 2, to_m(thickness), to_m(thickness), 0.5, True, False, True, True)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal base flange", sketch=sketch)
    # Some SOLIDWORKS builds invalidate the IModelDoc2 dispatch used to create
    # the base flange. Reacquire ActiveDoc before native body/feature readback.
    _, doc = require_part()
    sheet_features = _sheet_features(doc)
    if payload["ok"] and not any(bool(value(b, "IsSheetMetal")) for b in get_bodies(doc)):
        payload.update(ok=False, message="Base flange feature did not create a sheet-metal body.")
    elif payload["ok"] and sheet_features:
        payload["parameters"] = _read_parameters(sheet_features[-1])
        payload["sheet_metal"] = True
        payload.setdefault("data", {}).update(parameters=payload["parameters"], sheet_metal=True)
    return payload


FLANGE_POSITIONS = {
    "material_inside": 1, "material_outside": 2, "bend_outside": 3,
    "bend_centerline": 4, "bend_sharp": 5, "bend_tangent": 6,
}


def _edge_objects(doc, selection):
    indices = list((selection or {}).get("edges") or [])
    if not indices:
        raise RuntimeError("Select at least one base edge with selection.edges.")
    available = iter_edge_objects(doc)
    edges = []
    for raw in indices:
        index = int(raw)
        if not 0 <= index < len(available):
            raise RuntimeError(f"Edge index {index} is out of range (0..{len(available) - 1}).")
        edges.append(available[index][0])
    return edges


def _read_edge_flange(feature):
    definition = value(feature, "GetDefinition")
    return {
        "feature": str(value(feature, "Name")),
        "selected_edge_count": int(value(definition, "GetEdgeCount")),
        "height_mm": to_mm(float(value(definition, "OffsetDistance"))),
        "angle_degrees": math.degrees(float(value(definition, "BendAngle"))),
        "position_type": next((name for name, code in FLANGE_POSITIONS.items() if code == int(value(definition, "PositionType"))),
                              f"type_{int(value(definition, 'PositionType'))}"),
        "corner_gap_mm": to_mm(float(value(definition, "GapDistance"))),
        "use_default_bend_radius": bool(value(definition, "UseDefaultBendRadius")),
        "use_default_bend_allowance": bool(value(definition, "UseDefaultBendAllowance")),
        "use_default_bend_relief": bool(value(definition, "UseDefaultBendRelief")),
        "trim_side_bends": bool(value(definition, "UsePositionTrimSideBends")),
    }


@tool("edge_flange", "Create one native straight edge-flange feature on one or more base edges. Height and corner gap are mm; angle is degrees. A zero corner gap preserves the template default. Template bend radius, allowance and relief are preserved.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "height_mm": {"type": "number", "exclusiveMinimum": 0},
       "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180, "default": 90},
       "position_type": {"type": "string", "enum": list(FLANGE_POSITIONS), "default": "material_inside"},
       "corner_gap_mm": {"type": "number", "minimum": 0, "default": 0},
       "reverse_direction": {"type": "boolean", "default": False}, "name": {"type": "string"}},
      ["selection", "height_mm"])
def edge_flange(args):
    height = _positive(args["height_mm"], "height_mm")
    angle_degrees = float(args.get("angle_degrees", 90))
    gap = float(args.get("corner_gap_mm", 0))
    position = str(args.get("position_type", "material_inside"))
    if not math.isfinite(angle_degrees) or not 0 < angle_degrees < 180:
        raise RuntimeError("angle_degrees must be finite and between 0 and 180.")
    if not math.isfinite(gap) or gap < 0:
        raise RuntimeError("corner_gap_mm must be finite and nonnegative.")
    if position not in FLANGE_POSITIONS:
        raise RuntimeError(f"Unknown position_type '{position}'.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    edges = _edge_objects(doc, args.get("selection"))
    angle = math.radians(angle_degrees)
    reverse = bool(args.get("reverse_direction", False))
    sketches = []
    clear_selection(doc)
    try:
        for edge in edges:
            sketch = flag_methods(doc, "InsertSketchForEdgeFlange").InsertSketchForEdgeFlange(edge, angle, reverse)
            if sketch is None:
                raise RuntimeError("SOLIDWORKS could not create an edge-flange sketch for a selected edge.")
            sketch_manager = flag_methods(value(doc, "SketchManager"), "CreateLine", "InsertSketch")
            if value(sketch_manager, "ActiveSketch") is None:
                selectable(sketch).Select2(False, 0)
                flag_methods(doc, "EditSketch").EditSketch()
            active_sketch = value(sketch_manager, "ActiveSketch")
            clear_selection(doc)
            if not bool(selectable(edge).Select4(False, nothing())):
                raise RuntimeError("SOLIDWORKS could not select the flange edge in its profile sketch.")
            if not bool(flag_methods(sketch_manager, "SketchUseEdge").SketchUseEdge(False)):
                raise RuntimeError("SOLIDWORKS could not project the flange edge into its profile sketch.")
            segments = as_list(value(active_sketch, "GetSketchSegments"))
            if not segments:
                raise RuntimeError("The edge-flange profile has no projected edge.")
            projected = max(segments, key=lambda segment: float(value(segment, "GetLength")))
            start = value(projected, "GetStartPoint2"); end = value(projected, "GetEndPoint2")
            x1, y1 = float(value(start, "X")), float(value(start, "Y"))
            x2, y2 = float(value(end, "X")), float(value(end, "Y"))
            offset = -to_m(height) if reverse else to_m(height)
            profile = [
                sketch_manager.CreateLine(x1, y1, 0.0, x1, y1 + offset, 0.0),
                sketch_manager.CreateLine(x1, y1 + offset, 0.0, x2, y2 + offset, 0.0),
                sketch_manager.CreateLine(x2, y2 + offset, 0.0, x2, y2, 0.0),
            ]
            if any(item is None for item in profile):
                raise RuntimeError("SOLIDWORKS could not close the edge-flange profile.")
            sketch_manager.InsertSketch(True)
            sketches.append(active_sketch)
        manager = flag_methods(feature_manager(doc), "InsertSheetMetalEdgeFlange2")
        options = 1 | 32 | 128 | (2 if reverse else 0)
        feature = manager.InsertSheetMetalEdgeFlange2(
            dispatch_array(edges), dispatch_array(sketches), options, angle, 0.0,
            FLANGE_POSITIONS[position], to_m(height), 0, 0.0, 0.0, 0.0, 2, nothing())
        if feature is not None and gap > 0:
            definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
            if not bool(definition.AccessSelections(doc, nothing())):
                raise RuntimeError("The edge flange was created, but its gap definition could not be accessed.")
            modified = False
            try:
                definition.GapDistance = to_m(gap)
                modified = bool(feature.ModifyDefinition(definition, doc, nothing()))
            finally:
                if not modified:
                    definition.ReleaseSelectionAccess()
            if not modified:
                raise RuntimeError("The edge flange was created, but its requested corner gap was rejected.")
        rename_feature(feature, args.get("name"))
        payload = feature_result(doc, feature, "edge flange")
        if payload["ok"]:
            actual = _read_edge_flange(feature)
            payload["edge_flange"] = actual
            payload.setdefault("data", {})["edge_flange"] = actual
            correct = (actual["selected_edge_count"] == len(edges)
                       and math.isclose(actual["height_mm"], height, abs_tol=1e-6)
                       and math.isclose(actual["angle_degrees"], angle_degrees, abs_tol=1e-6)
                       and actual["position_type"] == position
                       and (gap == 0 or math.isclose(actual["corner_gap_mm"], gap, abs_tol=1e-6)))
            if not correct:
                payload.update(ok=False, message="Edge-flange readback differs from the requested definition.")
        return payload
    finally:
        clear_selection(doc)


HEM_TYPES = {"open": 0, "closed": 1, "teardrop": 2, "rolled": 3}
HEM_POSITIONS = {"material_inside": 0, "material_outside": 1}


def _read_hem(feature):
    definition = value(feature, "GetDefinition")
    return {
        "feature": str(value(feature, "Name")),
        "type": next((name for name, code in HEM_TYPES.items() if code == int(value(definition, "Type"))),
                     f"type_{int(value(definition, 'Type'))}"),
        "length_mm": to_mm(float(value(definition, "Length"))),
        "gap_mm": to_mm(float(value(definition, "GapDistance"))),
        "radius_mm": to_mm(float(value(definition, "Radius"))),
        "angle_degrees": math.degrees(float(value(definition, "Angle"))),
        "reverse": bool(value(definition, "ReverseDirection")),
    }


@tool("sheet_metal_hem", "Create a native hem on selected straight sheet-metal edges and read its definition back. Length, gap, radius and miter gap are mm; angle is degrees.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "hem_type": {"type": "string", "enum": list(HEM_TYPES), "default": "open"},
       "position": {"type": "string", "enum": list(HEM_POSITIONS), "default": "material_inside"},
       "length_mm": {"type": "number", "exclusiveMinimum": 0}, "gap_mm": {"type": "number", "minimum": 0, "default": 0},
       "angle_degrees": {"type": "number", "minimum": 0, "maximum": 360, "default": 180},
       "radius_mm": {"type": "number", "minimum": 0, "default": 0},
       "miter_gap_mm": {"type": "number", "minimum": 0, "default": 0},
       "reverse_direction": {"type": "boolean", "default": False}, "name": {"type": "string"}},
      ["selection", "length_mm"])
def sheet_metal_hem(args):
    length = _positive(args["length_mm"], "length_mm")
    numbers = {key: float(args.get(key, default)) for key, default in
               (("gap_mm", 0), ("angle_degrees", 180), ("radius_mm", 0), ("miter_gap_mm", 0))}
    if not all(math.isfinite(v) and v >= 0 for v in numbers.values()):
        raise RuntimeError("Hem gap, angle, radius and miter gap must be finite and nonnegative.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    count = apply_selection(doc, args["selection"])
    if count < 1:
        return result(False, "Select at least one straight sheet-metal edge.")
    manager = flag_methods(feature_manager(doc), "InsertSheetMetalHem2")
    feature = manager.InsertSheetMetalHem2(
        HEM_TYPES[str(args.get("hem_type", "open"))], HEM_POSITIONS[str(args.get("position", "material_inside"))],
        bool(args.get("reverse_direction", False)), to_m(length), to_m(numbers["gap_mm"]),
        math.radians(numbers["angle_degrees"]), to_m(numbers["radius_mm"]), to_m(numbers["miter_gap_mm"]),
        nothing(), True, 0, 0, True, 1.0, 0.0, 0.0)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal hem", selected_edges=count)
    if payload["ok"]:
        try:
            actual = _read_hem(feature)
            payload["hem"] = actual
            payload.setdefault("data", {})["hem"] = actual
            if actual["type"] != str(args.get("hem_type", "open")):
                payload.update(ok=False, message="Hem native readback differs from the requested type.")
        except Exception as exc:
            payload.update(ok=False, message=f"Hem was created but its native definition could not be verified: {exc}")
    clear_selection(doc)
    return payload


def _read_break_corner(feature, doc):
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not bool(definition.AccessSelections(doc, nothing())):
        raise RuntimeError("native selections could not be accessed")
    try:
        readback = {"feature": str(value(feature, "Name")),
                    "type": str(feature_property(feature, "GetTypeName2", "")),
                    "distance_mm": to_mm(float(value(definition, "Distance"))),
                    "entity_count": int(value(definition, "GetEntitiesCount"))}
        native_type = safe(definition, "Type")
        if native_type is not None:
            readback["corner_type_code"] = int(native_type)
        return readback
    finally:
        definition.ReleaseSelectionAccess()


@tool("sheet_metal_break_corner", "Create a native folded-state break corner on selected edges or flange faces and verify the resulting feature.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "corner_type": {"type": "string", "enum": ["chamfer", "fillet"]},
       "size_mm": {"type": "number", "exclusiveMinimum": 0}, "name": {"type": "string"}},
      ["selection", "corner_type", "size_mm"])
def sheet_metal_break_corner(args):
    size = _positive(args["size_mm"], "size_mm")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    count = apply_selection(doc, args["selection"])
    if count < 1:
        return result(False, "Select at least one sheet-metal edge or flange face.")
    before = {str(value(f, "Name")) for f in iter_feature_objects(doc)}
    flag_methods(doc, "InsertSheetMetalBreakCorner").InsertSheetMetalBreakCorner(
        0 if args["corner_type"] == "chamfer" else 1, to_m(size))
    feature = next((f for f in reversed(iter_feature_objects(doc)) if str(value(f, "Name")) not in before), None)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal break corner", selected=count)
    if payload["ok"]:
        kind = str(feature_property(feature, "GetTypeName2", ""))
        try:
            readback = _read_break_corner(feature, doc)
            payload["break_corner"] = readback
            payload.setdefault("data", {})["break_corner"] = readback
            expected_type = 0 if args["corner_type"] == "chamfer" else 1
            correct = (kind == "BreakCorner" and readback["entity_count"] >= count
                       and math.isclose(readback["distance_mm"], size, abs_tol=1e-6)
                       and ("corner_type_code" not in readback or readback["corner_type_code"] == expected_type))
            if not correct:
                payload.update(ok=False, message="Break-corner native definition readback differs from the request.")
        except Exception as exc:
            payload.update(ok=False, message=f"Break corner was created but its native definition could not be verified: {exc}")
    clear_selection(doc)
    return payload


CORNER_RELIEF_TYPES = {"circular": 0, "square": 1, "bend_waist": 2}


@tool("sheet_metal_corner_relief", "Create a native corner-trim relief on selected sheet-metal corners and read the break-corner definition back. Dimensions are mm.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "internal_corners_only": {"type": "boolean", "default": False},
       "break_type": {"type": "string", "enum": ["chamfer", "fillet"], "default": "chamfer"},
       "break_distance_mm": {"type": "number", "minimum": 0, "default": 0},
       "relief_type": {"type": "string", "enum": list(CORNER_RELIEF_TYPES)},
       "relief_size_mm": {"type": "number", "exclusiveMinimum": 0}, "name": {"type": "string"}},
      ["selection", "relief_type", "relief_size_mm"])
def sheet_metal_corner_relief(args):
    size = _positive(args["relief_size_mm"], "relief_size_mm")
    distance = float(args.get("break_distance_mm", 0))
    if not math.isfinite(distance) or distance < 0:
        raise RuntimeError("break_distance_mm must be finite and nonnegative.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    count = apply_selection(doc, args["selection"])
    if count < 1:
        return result(False, "Select at least one sheet-metal corner edge or face.")
    manager = flag_methods(feature_manager(doc), "InsertSheetMetalCornerTrim")
    feature = manager.InsertSheetMetalCornerTrim(
        int(bool(args.get("internal_corners_only", False))),
        0 if str(args.get("break_type", "chamfer")) == "chamfer" else 1,
        to_m(distance), CORNER_RELIEF_TYPES[str(args["relief_type"])], to_m(size))
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal corner relief", selected=count)
    if payload["ok"]:
        try:
            definition = value(feature, "GetDefinition")
            entity_count = int(value(definition, "GetEntitiesCount"))
            payload["corner_relief"] = {
                "feature": str(value(feature, "Name")),
                "type": str(feature_property(feature, "GetTypeName2", "")),
                "entity_count": entity_count,
                "relief_type": str(args["relief_type"]),
                "relief_size_mm": size,
                "break_distance_mm": distance,
            }
            payload.setdefault("data", {})["corner_relief"] = payload["corner_relief"]
            if entity_count < 1:
                payload.update(ok=False, message="Corner relief exists, but native definition has no target entities.")
        except Exception as exc:
            payload.update(ok=False, message=f"Corner relief was created but its native definition could not be verified: {exc}")
    clear_selection(doc)
    return payload


CLOSED_CORNER_TYPES = {"butt": 0, "overlap": 1, "underlap": 2}


@tool("sheet_metal_closed_corner", "Create and configure a native closed corner from exact faces-to-extend and faces-to-match selections, then read its definition back. Gap is mm.",
      {**EDIT_TOKEN, "faces_to_extend": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
       "faces_to_match": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
       "corner_type": {"type": "string", "enum": list(CLOSED_CORNER_TYPES), "default": "butt"},
       "gap_mm": {"type": "number", "minimum": 0, "default": 0},
       "open_bend_region": {"type": "boolean", "default": False},
       "overlap_ratio": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
       "name": {"type": "string"}}, ["faces_to_extend", "faces_to_match"])
def sheet_metal_closed_corner(args):
    gap = float(args.get("gap_mm", 0))
    ratio = float(args.get("overlap_ratio", 0.5))
    if not math.isfinite(gap) or gap < 0 or not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise RuntimeError("gap_mm must be nonnegative and overlap_ratio must be between 0 and 1.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    clear_selection(doc)
    extend_count = apply_selection(doc, {"faces": args["faces_to_extend"]}, mark=1)
    match_count = apply_selection(doc, {"faces": args["faces_to_match"]}, mark=1073741824, append=True)
    if extend_count != len(args["faces_to_extend"]) or match_count != len(args["faces_to_match"]):
        clear_selection(doc)
        return result(False, "Could not select every requested closed-corner face.")
    before = {str(value(f, "Name")) for f in iter_feature_objects(doc)}
    flag_methods(doc, "InsertSheetMetalClosedCorner").InsertSheetMetalClosedCorner()
    feature = next((f for f in reversed(iter_feature_objects(doc)) if str(value(f, "Name")) not in before), None)
    if feature is None:
        clear_selection(doc)
        return result(False, "SOLIDWORKS did not create a closed-corner feature.")
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        clear_selection(doc)
        return result(False, "Closed corner was created, but its definition could not be accessed.")
    modified = False
    try:
        definition.CornerType = CLOSED_CORNER_TYPES[str(args.get("corner_type", "butt"))]
        definition.GapDistance = to_m(gap)
        definition.OpenBendRegion = bool(args.get("open_bend_region", False))
        definition.OverlapUnderlapRatio = ratio
        modified = bool(feature.ModifyDefinition(definition, doc, nothing()))
    finally:
        if not modified:
            definition.ReleaseSelectionAccess()
    rename_feature(feature, args.get("name"))
    rebuild(doc)
    actual = value(feature, "GetDefinition")
    faces = as_list(value(actual, "Faces"))
    readback = {"feature": str(value(feature, "Name")),
                "type": str(feature_property(feature, "GetTypeName2", "")),
                "corner_type": int(value(actual, "CornerType")),
                "gap_mm": to_mm(float(value(actual, "GapDistance"))),
                "open_bend_region": bool(value(actual, "OpenBendRegion")),
                "overlap_ratio": float(value(actual, "OverlapUnderlapRatio")),
                "face_count": len(faces)}
    correct = (modified and readback["corner_type"] == CLOSED_CORNER_TYPES[str(args.get("corner_type", "butt"))]
               and math.isclose(readback["gap_mm"], gap, abs_tol=1e-6)
               and readback["open_bend_region"] == bool(args.get("open_bend_region", False))
               and math.isclose(readback["overlap_ratio"], ratio, abs_tol=1e-9)
               and readback["face_count"] >= len(args["faces_to_extend"]))
    problems = whats_wrong(doc)
    clear_selection(doc)
    return result(correct and not problems,
                  "Created and verified a native closed corner." if correct and not problems else
                  "Closed-corner native readback or rebuild verification did not match the request.",
                  closed_corner=readback, problems=problems)


JOG_DIMENSION_POSITIONS = {"inside_offset": 1, "outside_offset": 2, "overall": 3}
JOG_POSITIONS = {"bend_centerline": 1, "material_inside": 2, "material_outside": 3, "bend_outside": 4}


@tool("sheet_metal_jog", "Create a native sheet-metal jog from a selected bend-line sketch and fixed face, then read the jog definition back. Angle is degrees; radius and offset are mm.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
       "radius_mm": {"type": "number", "minimum": 0}, "offset_mm": {"type": "number", "exclusiveMinimum": 0},
       "reverse_direction": {"type": "boolean", "default": False},
       "fix_projected_length": {"type": "boolean", "default": False},
       "dimension_position": {"type": "string", "enum": list(JOG_DIMENSION_POSITIONS), "default": "overall"},
       "bend_position": {"type": "string", "enum": list(JOG_POSITIONS), "default": "material_inside"},
       "name": {"type": "string"}}, ["selection", "angle_degrees", "radius_mm", "offset_mm"])
def sheet_metal_jog(args):
    angle = float(args["angle_degrees"])
    radius = float(args["radius_mm"])
    offset = _positive(args["offset_mm"], "offset_mm")
    if not math.isfinite(angle) or not 0 < angle < 180 or not math.isfinite(radius) or radius < 0:
        raise RuntimeError("Jog angle must be between 0 and 180 degrees and radius must be nonnegative.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    count = apply_selection(doc, args["selection"])
    if count < 2:
        return result(False, "Select the jog bend-line sketch and a fixed sheet-metal face.")
    before = {str(value(f, "Name")) for f in iter_feature_objects(doc)}
    flag_methods(doc, "InsertSheetMetalJog").InsertSheetMetalJog(
        math.radians(angle), to_m(radius), to_m(offset), bool(args.get("reverse_direction", False)),
        bool(args.get("fix_projected_length", False)),
        JOG_DIMENSION_POSITIONS[str(args.get("dimension_position", "overall"))],
        JOG_POSITIONS[str(args.get("bend_position", "material_inside"))])
    feature = next((f for f in reversed(iter_feature_objects(doc)) if str(value(f, "Name")) not in before), None)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal jog", selected=count)
    if payload["ok"]:
        try:
            definition = value(feature, "GetDefinition")
            actual = {"feature": str(value(feature, "Name")),
                      "type": str(feature_property(feature, "GetTypeName2", "")),
                      "angle_degrees": math.degrees(float(value(definition, "JogAngle"))),
                      "radius_mm": to_mm(float(value(definition, "BendRadius"))),
                      "offset_mm": to_mm(float(value(definition, "OffsetDistance"))),
                      "dimension_position": int(value(definition, "DimensionPositionType")),
                      "bend_position": int(value(definition, "JogPositionType"))}
            payload["jog"] = actual
            payload.setdefault("data", {})["jog"] = actual
            correct = (math.isclose(actual["angle_degrees"], angle, abs_tol=1e-6)
                       and math.isclose(actual["radius_mm"], radius, abs_tol=1e-6)
                       and math.isclose(actual["offset_mm"], offset, abs_tol=1e-6))
            if not correct:
                payload.update(ok=False, message="Jog native readback differs from the request.")
        except Exception as exc:
            payload.update(ok=False, message=f"Jog was created but its native definition could not be verified: {exc}")
    clear_selection(doc)
    return payload


RIP_DIRECTIONS = {"current": 16, "other": 32, "both": 64}


def _read_rip(feature, doc):
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not bool(definition.AccessSelections(doc, nothing())):
        raise RuntimeError("native selections could not be accessed")
    try:
        edges = as_list(value(definition, "Edges"))
        return {"feature": str(value(feature, "Name")),
                "type": str(feature_property(feature, "GetTypeName2", "")),
                "gap_mm": to_mm(float(value(definition, "Gap"))),
                "edge_count": int(value(definition, "GetEdgesCount")),
                "direction_codes": [int(definition.GetDirection(edge)) for edge in edges]}
    finally:
        definition.ReleaseSelectionAccess()


@tool("sheet_metal_rip", "Create a native rip along selected model edges or sketch segments. Gap is mm; direction maps to the documented selection mark.",
      {**EDIT_TOKEN, "selection": SELECTION_SCHEMA, "gap_mm": {"type": "number", "exclusiveMinimum": 0},
       "direction": {"type": "string", "enum": list(RIP_DIRECTIONS), "default": "both"},
       "name": {"type": "string"}}, ["selection", "gap_mm"])
def sheet_metal_rip(args):
    gap = _positive(args["gap_mm"], "gap_mm")
    direction = str(args.get("direction", "both"))
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    count = apply_selection(doc, args["selection"], mark=RIP_DIRECTIONS[direction])
    if count < 1:
        return result(False, "Select at least one edge or sketch segment to rip.")
    before = {str(value(f, "Name")) for f in iter_feature_objects(doc)}
    flag_methods(doc, "InsertRip").InsertRip(to_m(gap))
    feature = next((f for f in reversed(iter_feature_objects(doc)) if str(value(f, "Name")) not in before), None)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sheet-metal rip", direction=direction, selected=count)
    if payload["ok"]:
        kind = str(feature_property(feature, "GetTypeName2", ""))
        try:
            readback = _read_rip(feature, doc)
            payload["rip"] = readback
            payload.setdefault("data", {})["rip"] = readback
            correct = (kind == "Rip" and readback["edge_count"] >= count
                       and len(readback["direction_codes"]) == readback["edge_count"]
                       and math.isclose(readback["gap_mm"], gap, abs_tol=1e-6))
            if not correct:
                payload.update(ok=False, message="Rip native definition readback differs from the request.")
        except Exception as exc:
            payload.update(ok=False, message=f"Rip was created but its native definition could not be verified: {exc}")
    clear_selection(doc)
    return payload


BEND_POSITIONS = {"material_inside": 0, "material_outside": 1, "bend_outside": 2, "bend_centerline": 3}


@tool("sheet_metal_sketched_bend", "Create a native sketched bend from a named bend-line sketch. Angle is degrees and radius is mm; native feature identity and definition are read back.",
      {**EDIT_TOKEN, "sketch_name": {"type": "string"}, "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
       "radius_mm": {"type": "number", "minimum": 0}, "use_default_radius": {"type": "boolean", "default": True},
       "reverse_direction": {"type": "boolean", "default": False},
       "position": {"type": "string", "enum": list(BEND_POSITIONS), "default": "material_inside"},
       "name": {"type": "string"}}, ["sketch_name", "angle_degrees"])
def sheet_metal_sketched_bend(args):
    angle = float(args["angle_degrees"])
    radius = float(args.get("radius_mm", 0))
    if not math.isfinite(angle) or not 0 < angle < 180 or not math.isfinite(radius) or radius < 0:
        raise RuntimeError("Bend angle must be between 0 and 180 degrees and radius must be nonnegative.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    sketch = select_sketch_for_feature(doc, str(args["sketch_name"]))
    manager = feature_manager(doc)
    feature = flag_methods(manager, "InsertSheetMetal3dBend").InsertSheetMetal3dBend(
        math.radians(angle), bool(args.get("use_default_radius", True)), to_m(radius),
        bool(args.get("reverse_direction", False)), BEND_POSITIONS[str(args.get("position", "material_inside"))], nothing())
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "sketched bend", sketch=sketch)
    if payload["ok"]:
        kind = str(feature_property(feature, "GetTypeName2", ""))
        definition = value(feature, "GetDefinition")
        payload["sketched_bend"] = {"feature": str(value(feature, "Name")), "type": kind,
            "angle_degrees": math.degrees(float(value(definition, "BendAngle"))),
            "radius_mm": to_mm(float(value(definition, "BendRadius")))}
        payload.setdefault("data", {})["sketched_bend"] = payload["sketched_bend"]
        if kind not in {"SketchBend", "OneBend", "SM3dBend"}:
            payload.update(ok=False, message="A feature appeared, but native sketched-bend identity was not confirmed.")
    clear_selection(doc)
    return payload


# SM3dBend is the container created by InsertSheetMetal3dBend.  Its native
# SketchBend subfeature is the entity accepted by IFoldsFeatureData.Bends;
# exposing both makes one physical bend appear twice and produces ambiguous
# unfold/fold selections.
BEND_SELECTABLE_TYPES = {"OneBend", "SketchBend", "EdgeBend", "Jog"}


def _bend_features(doc, names, all_bends):
    available = [f for f in _all_feature_objects(doc)
                 if str(feature_property(f, "GetTypeName2", "")) in BEND_SELECTABLE_TYPES]
    if all_bends:
        if not available:
            raise RuntimeError("No native bend features were found.")
        return available
    requested = [str(name) for name in (names or [])]
    if not requested:
        raise RuntimeError("Pass bend_feature_names or set all_bends=true.")
    resolved = []
    for name in requested:
        feature = next((candidate for candidate in available if str(value(candidate, "Name")) == name), None)
        if feature is None or str(feature_property(feature, "GetTypeName2", "")) not in BEND_SELECTABLE_TYPES:
            raise RuntimeError(f"'{name}' is not a native bend feature in the current part.")
        resolved.append(feature)
    return resolved


def _read_fold_data(feature, doc):
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not bool(definition.AccessSelections(doc, nothing())):
        raise RuntimeError("native fold selections could not be accessed")
    try:
        bends = as_list(value(definition, "Bends"))
        try:
            bend_count = int(value(flag_methods(definition, "IGetBendsCount"), "IGetBendsCount"))
        except Exception:
            bend_count = len(bends)
        return {"type": str(feature_property(feature, "GetTypeName2", "")),
                "bend_count": bend_count, "fixed_face_present": value(definition, "FixedFace") is not None}
    finally:
        definition.ReleaseSelectionAccess()


def _fold_operation(args, fold):
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    fixed = int(args["fixed_face_index"])
    bends = _bend_features(doc, args.get("bend_feature_names"), bool(args.get("all_bends", False)))
    clear_selection(doc)
    if fold:
        unfold = find_feature(doc, str(args["unfold_feature_name"]))
        if (unfold is None or str(feature_property(unfold, "GetTypeName2", "")) not in {"UnFold", "Unfold"}
                or not bool(selectable(unfold).Select2(False, 0))):
            return result(False, "Could not select the named unfold feature.")
    if apply_selection(doc, {"faces": [fixed]}, mark=1, append=fold) != 1:
        return result(False, "Could not select the fixed face.")
    selected = 0
    for bend in bends:
        selected += int(bool(selectable(bend).Select2(True, 4)))
    if selected != len(bends):
        clear_selection(doc)
        return result(False, "Could not select every requested bend feature.")
    before = {str(value(f, "Name")) for f in iter_feature_objects(doc)}
    value(doc, "InsertSheetMetalFold" if fold else "InsertSheetMetalUnfold")
    feature = next((f for f in reversed(iter_feature_objects(doc)) if str(value(f, "Name")) not in before), None)
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "fold" if fold else "unfold", fixed_face_index=fixed,
                             bends=[str(value(f, "Name")) for f in bends])
    if payload["ok"]:
        kind = str(feature_property(feature, "GetTypeName2", ""))
        payload["fold_data"] = _read_fold_data(feature, doc)
        payload.setdefault("data", {})["fold_data"] = payload["fold_data"]
        valid_types = {"Fold"} if fold else {"UnFold", "Unfold"}
        if kind not in valid_types or payload["fold_data"]["bend_count"] != len(bends) or not payload["fold_data"]["fixed_face_present"]:
            payload.update(ok=False, message="Native fold/unfold readback differs from the requested bends.")
    clear_selection(doc)
    return payload


FOLD_SCHEMA = {**EDIT_TOKEN, "fixed_face_index": {"type": "integer", "minimum": 0},
               "bend_feature_names": {"type": "array", "items": {"type": "string"}},
               "all_bends": {"type": "boolean", "default": False}, "name": {"type": "string"}}


@tool("sheet_metal_unfold", "Create a native Unfold feature using a fixed face (selection mark 1) and exact bend features (mark 4). This is distinct from FlatPattern suppression.", FOLD_SCHEMA, ["fixed_face_index"])
def sheet_metal_unfold(args):
    return _fold_operation(args, False)


@tool("sheet_metal_fold", "Create a native Fold feature after an Unfold, using the same fixed face and bend features. This is distinct from FlatPattern suppression.",
      {**FOLD_SCHEMA, "unfold_feature_name": {"type": "string"}}, ["fixed_face_index", "unfold_feature_name"])
def sheet_metal_fold(args):
    return _fold_operation(args, True)


@tool("sheet_metal_normal_cut", "Create a cut-extrude from a named sketch, enable the native sheet-metal NormalCut option, rebuild, and verify the feature definition. Depth is mm.",
      {**EDIT_TOKEN, "sketch_name": {"type": "string"}, "depth_mm": {"type": "number", "exclusiveMinimum": 0, "default": 10},
       "end_condition": {"type": "string", "enum": ["blind", "through_all", "through_next", "up_to_surface", "offset_from_surface", "mid_plane", "through_all_both"], "default": "through_all"},
       "reverse": {"type": "boolean", "default": False},
       "optimize_geometry": {"type": "boolean", "default": True}, "name": {"type": "string"}},
      ["sketch_name"])
def sheet_metal_normal_cut(args):
    if "depth_mm" in args:
        _positive(args["depth_mm"], "depth_mm")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    temporary = str(args.get("name") or f"MCP_NormalCut_{uuid.uuid4().hex[:8]}")
    created = sw_feature.cut_extrude({"sketch_name": str(args["sketch_name"]),
        "depth_mm": float(args.get("depth_mm", 10)), "end_condition": str(args.get("end_condition", "through_all")),
        "reverse": bool(args.get("reverse", False)), "name": temporary})
    if not created.get("ok"):
        return created
    feature = find_feature(doc, temporary)
    if feature is None:
        return result(False, "The cut was created but its feature could not be resolved for NormalCut editing.")
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        return result(False, "The cut was created but its definition could not be accessed for NormalCut editing.")
    modified = False
    try:
        definition.NormalCut = True
        definition.OptimizeGeometry = bool(args.get("optimize_geometry", True))
        modified = bool(feature.ModifyDefinition(definition, doc, nothing()))
    finally:
        if not modified:
            value(definition, "ReleaseSelectionAccess")
    rebuild(doc)
    actual = value(feature, "GetDefinition")
    normal = bool(value(actual, "NormalCut"))
    optimized = bool(value(actual, "OptimizeGeometry"))
    problems = whats_wrong(doc)
    return result(modified and normal and optimized == bool(args.get("optimize_geometry", True)) and not problems,
                  "Created and verified a native normal cut." if modified and normal else
                  "The cut remains, but native NormalCut readback did not match the request.",
                  feature=str(value(feature, "Name")), normal_cut=normal,
                  optimize_geometry=optimized, problems=problems)


@tool("list_sheet_metal_features", "Read-only: list native sheet-metal definitions, flat patterns and current suppression states.")
def list_sheet_metal_features(args):
    _, doc = require_part()
    return result(True, "Read sheet-metal features.", sheet_metal=[_read_parameters(f) for f in _sheet_features(doc)],
                  flat_patterns=[{"feature": str(value(f, "Name")), "suppressed": _suppressed(f)} for f in _flat_features(doc)],
                  bends=[{"feature": str(value(f, "Name")), "type": str(feature_property(f, "GetTypeName2", ""))}
                         for f in _bend_features(doc, None, True)] if any(
                             str(feature_property(f, "GetTypeName2", "")) in BEND_SELECTABLE_TYPES
                             for f in _all_feature_objects(doc)) else [])


def _sheet_feature(doc, name):
    if not name:
        template = value(extension(doc), "GetTemplateSheetMetal")
        if template is None:
            raise RuntimeError("The active part has no sheet-metal defaults.")
        return template
    available = _sheet_features(doc)
    if name:
        available = [f for f in available if str(value(f, "Name")) == name]
    if len(available) != 1:
        raise RuntimeError("Select an exact sheet-metal feature name from list_sheet_metal_features.")
    return available[0]


@tool("get_sheet_metal_parameters", "Read-only: read sheet-metal thickness, bend radius and K-factor. Omit feature_name for document defaults, or specify a body definition from list_sheet_metal_features.", {"feature_name": {"type": "string"}})
def get_sheet_metal_parameters(args):
    _, doc = require_part()
    return result(True, "Read sheet-metal parameters.", parameters=_read_parameters(_sheet_feature(doc, args.get("feature_name"))))


@tool("set_sheet_metal_parameters", "Edit sheet-metal thickness/radius/K-factor and read values back. Omit feature_name to edit document defaults; specify a body definition to override its defaults. Lengths are mm.",
      {**EDIT_TOKEN, "feature_name": {"type": "string"}, "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
       "bend_radius_mm": {"type": "number", "minimum": 0}, "k_factor": {"type": "number", "minimum": 0, "maximum": 1}})
def set_sheet_metal_parameters(args):
    changes = {}
    for key, member in (("thickness_mm", "Thickness"), ("bend_radius_mm", "BendRadius"), ("k_factor", "KFactor")):
        if key not in args:
            continue
        raw = float(args[key])
        if not math.isfinite(raw) or (raw <= 0 if key == "thickness_mm" else raw < 0) or (key == "k_factor" and raw > 1):
            raise RuntimeError(f"Invalid {key}.")
        changes[member] = to_m(raw) if key.endswith("_mm") else raw
    if not changes:
        raise RuntimeError("Specify at least one sheet-metal parameter to change.")
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    feature = _sheet_feature(doc, args.get("feature_name"))
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        return result(False, "Could not access the sheet-metal definition.")
    modified = False
    try:
        if args.get("feature_name"):
            flag_methods(definition, "SetOverrideDefaultParameter2")
            if "Thickness" in changes or "BendRadius" in changes:
                definition.SetOverrideDefaultParameter2(0, True)
            if "KFactor" in changes:
                definition.SetOverrideDefaultParameter2(1, True)
        for member, raw in changes.items():
            setattr(definition, member, raw)
        modified = bool(flag_methods(feature, "ModifyDefinition").ModifyDefinition(definition, doc, nothing()))
    finally:
        if not modified:
            value(definition, "ReleaseSelectionAccess")
    rebuild(doc)
    actual = _read_parameters(feature)
    correct = all(math.isclose(actual[key], float(args[key]), rel_tol=1e-6, abs_tol=1e-6) for key in ("thickness_mm", "bend_radius_mm", "k_factor") if key in args)
    problems = whats_wrong(doc)
    return result(modified and correct and not problems, "Updated sheet-metal parameters." if modified and correct else "Sheet-metal parameter readback differs or update failed.", parameters=actual, problems=problems)


@tool("set_flat_pattern", "Flatten or refold sheet metal by changing native FlatPattern suppression in the current configuration. Re-list topology afterwards.",
      {**EDIT_TOKEN, "flat": {"type": "boolean"}, "feature_name": {"type": "string"}}, ["flat"])
def set_flat_pattern(args):
    _, doc = require_part()
    _guard_saved_document_edit(doc, args)
    features = _flat_features(doc)
    if args.get("feature_name"):
        features = [f for f in features if str(value(f, "Name")) == str(args["feature_name"])]
    if not features:
        return result(False, "No matching FlatPattern feature exists.")
    desired = not bool(args["flat"])
    actual = []
    for feature in features:
        flag_methods(feature, "SetSuppression2").SetSuppression2(0 if desired else 1, 1, empty_variant())
        rebuild(doc)
        actual.append({"feature": str(value(feature, "Name")), "suppressed": _suppressed(feature)})
    clear_selection(doc)
    problems = whats_wrong(doc)
    return result(all(item["suppressed"] == desired for item in actual) and not problems, "Updated flat-pattern state.", flat_patterns=actual, problems=problems)


def _inspect_dxf(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="ascii", errors="ignore").splitlines()
    pairs = [(lines[index].strip(), lines[index + 1].strip()) for index in range(0, len(lines) - 1, 2)]
    in_entities = False; current: dict[str, str] | None = None; entities: list[dict[str, str]] = []
    for code, raw in pairs:
        if code == "0" and raw == "SECTION":
            current = None
        elif code == "2" and raw == "ENTITIES":
            in_entities = True
        elif code == "0" and raw == "ENDSEC":
            in_entities = False; current = None
        elif in_entities and code == "0":
            current = {"type": raw, "layer": ""}; entities.append(current)
        elif in_entities and current is not None and code == "8":
            current["layer"] = raw
    geometry = [entry for entry in entities if entry["type"] in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE"}]
    def is_bend_layer(layer: str) -> bool:
        normalized = layer.strip().upper().replace("_", "-")
        return "BEND" in normalized or normalized in {"UP", "DOWN"}
    bend = [entry for entry in geometry if is_bend_layer(entry["layer"])]
    return {"entity_count": len(geometry), "bend_entity_count": len(bend),
            "layers": sorted({entry["layer"] for entry in geometry if entry["layer"]})}


@tool("export_flat_pattern", "Export a saved sheet-metal part's flat pattern as DXF under the output root. Optionally include bend lines. Verifies the ENTITIES section and bend-layer entities when the model contains bends. The source part must already be saved.",
      {"path": {"type": "string"}, "bend_lines": {"type": "boolean", "default": True}, "overwrite": {"type": "boolean", "default": False}}, ["path"])
def export_flat_pattern(args):
    _, doc = require_part()
    model = str(value(doc, "GetPathName") or "")
    if not model or not Path(model).is_file():
        return result(False, "Save the sheet-metal part before exporting its flat pattern.")
    if not any(bool(value(body, "IsSheetMetal")) for body in get_bodies(doc)):
        return result(False, "The active part has no sheet-metal bodies.")
    output = validated_output_path(str(args["path"]), {".dxf"}, bool(args.get("overwrite", False)))
    options = 1 | (4 if args.get("bend_lines", True) else 0)
    clear_selection(doc)
    exported = bool(flag_methods(doc, "ExportToDWG2").ExportToDWG2(str(output), model, 1, True, empty_variant(), False, False, options, empty_variant()))
    inspection = {"entity_count": 0, "bend_entity_count": 0, "layers": []}
    valid = output.is_file() and output.stat().st_size > 0
    if valid:
        inspection = _inspect_dxf(output)
        valid = int(inspection["entity_count"]) > 0
    bend_expected = bool(args.get("bend_lines", True)) and any(
        str(feature_property(feature, "GetTypeName2", "")) in BEND_SELECTABLE_TYPES
        for feature in _all_feature_objects(doc))
    bend_valid = not bend_expected or int(inspection["bend_entity_count"]) > 0
    ok = exported and valid and bend_valid
    message = "Exported and verified flat-pattern DXF." if ok else (
        "Flat-pattern DXF contains no bend-layer entities for a model with bends." if valid and not bend_valid else
        "Flat-pattern export did not produce a valid DXF entity section.")
    return result(ok, message, path=str(output), bend_lines_requested=bool(args.get("bend_lines", True)),
                  bend_lines_expected=bend_expected, **inspection)
