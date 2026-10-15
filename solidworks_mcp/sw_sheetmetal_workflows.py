# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");

"""Verified sheet-metal workflows layered over the native primitives."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from . import sw_feature, sw_inspect, sw_sheetmetal, sw_sketch
from .sw_core import (
    active_document, apply_transform, as_list, clear_selection, dispatch_array, document_type,
    enumerate_edges, enumerate_faces, feature_property, find_feature, flag_methods, get_bodies,
    iter_edge_objects, iter_feature_objects, persistent_reference_id, rebuild, resolve_sketch, result, safe,
    running_app, sketch_segment_objects, to_m, tool, value, whats_wrong,
)


PROFILE_ENV = "SW_MCP_SHEETMETAL_TEMPLATE"
DIMENSION_MODES = ["finished_outer", "flat_blank"]
PROFILE = {
    "name": "standard_2026",
    "template_label": "2026 plaat",
    "preferred_plane": "front",
    "origin": "corner",
    "allowance_policy": "template",
    "relief": {"type": "rectangular", "ratio_to_thickness": 1.0},
    "dxf": {"bend_lines": True},
}


def _finite_positive(raw: Any, name: str) -> float:
    number = float(raw)
    if not math.isfinite(number) or number <= 0:
        raise RuntimeError(f"{name} must be finite and greater than zero.")
    return number


def _template_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get(PROFILE_ENV)
    if explicit:
        candidates.append(Path(explicit))
    root = os.environ.get("SW_MCP_TEMPLATE_DIR")
    if root and Path(root).is_dir():
        candidates.extend(sorted(Path(root).glob("*.prtdot")))
        candidates.extend(sorted(Path(root).glob("**/*.prtdot")))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _resolve_template() -> Path | None:
    candidates = _template_candidates()
    explicit = os.environ.get(PROFILE_ENV)
    if explicit:
        path = Path(explicit)
        return path if path.is_file() and path.suffix.casefold() == ".prtdot" else None
    label = PROFILE["template_label"].casefold()
    return next((path for path in candidates if path.is_file() and label in path.stem.casefold()), None)


@tool("list_sheet_metal_profiles", "Read-only: list configured sheet-metal workflow profiles and whether their templates resolve.", {})
def list_sheet_metal_profiles(args: dict[str, Any]) -> dict[str, Any]:
    template = _resolve_template()
    profile = dict(PROFILE)
    profile.update(template_available=template is not None, template_path=str(template) if template else "",
                   template_environment=PROFILE_ENV)
    return result(True, "Read sheet-metal workflow profiles.", profiles=[profile])


def _document_identity(doc: Any) -> dict[str, Any]:
    configuration = ""
    try:
        configuration = str(value(value(doc, "ConfigurationManager"), "ActiveConfiguration").Name)
    except Exception:
        pass
    return {
        "title": str(value(doc, "GetTitle") or ""),
        "path": str(value(doc, "GetPathName") or ""),
        "configuration": configuration,
    }


def _snapshot() -> dict[str, Any]:
    _, doc = active_document()
    if document_type(doc) != 1:
        raise RuntimeError("The active document must be a part.")
    bounds = sw_inspect.get_bounding_box({})
    bodies = [body for body in get_bodies(doc) if bool(value(body, "IsSheetMetal"))]
    features = []
    for feature in iter_feature_objects(doc):
        kind = str(feature_property(feature, "GetTypeName2", ""))
        if kind in {"SheetMetal", "FlatPattern", "EdgeFlange", "Hem", "Jog", "SketchBend", "Unfold", "Fold",
                    "Rip", "ClosedCorner", "BreakCorner", "CornerTrim", "Cut"}:
            entry = {"name": str(value(feature, "Name")), "type": kind,
                     "persistent_reference": persistent_reference_id(doc, feature).hex()}
            stamp = safe(feature, "GetUpdateStamp")
            if stamp is not None:
                entry["update_stamp"] = int(stamp)
            features.append(entry)
    mass = sw_inspect.get_mass_properties({})
    flats = [{"feature": str(value(f, "Name")), "suppressed": sw_sheetmetal._suppressed(f),
              "persistent_reference": persistent_reference_id(doc, f).hex()}
             for f in sw_sheetmetal._flat_features(doc)]
    return {
        "document": _document_identity(doc),
        "sheet_metal_body_count": len(bodies),
        "features": features,
        "topology": {
            "face_references": sorted(persistent_reference_id(doc, entry["_obj"]).hex()
                                      for entry in enumerate_faces(doc)),
            "edge_references": sorted(persistent_reference_id(doc, entry["_obj"]).hex()
                                      for entry in enumerate_edges(doc)),
        },
        "parameters": [sw_sheetmetal._read_parameters(f) for f in sw_sheetmetal._sheet_features(doc)],
        "flat_patterns": flats,
        "folded_state": not any(not item["suppressed"] for item in flats),
        "bounding_box": bounds.get("data", {}) if bounds.get("ok") else None,
        "mass_properties": mass.get("data", {}) if mass.get("ok") else None,
        "problems": whats_wrong(doc),
    }


def _token(snapshot: dict[str, Any]) -> str:
    packed = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


@tool("inspect_sheet_metal_part", "Read-only: inspect sheet-metal bodies, native definitions, feature state, folded bounds and rebuild problems.", {})
def inspect_sheet_metal_part(args: dict[str, Any]) -> dict[str, Any]:
    snapshot = _snapshot()
    return result(True, "Inspected the active sheet-metal part.", snapshot=snapshot, edit_token=_token(snapshot))


@tool("inspect_sheet_metal_edit", "Read-only: produce the current sheet-metal snapshot and edit token required by guarded editing workflows.", {})
def inspect_sheet_metal_edit(args: dict[str, Any]) -> dict[str, Any]:
    return inspect_sheet_metal_part(args)


def require_edit_token(raw: Any) -> dict[str, Any]:
    snapshot = _snapshot()
    if not raw or str(raw) != _token(snapshot):
        raise RuntimeError("The edit token is stale or belongs to a different document/configuration. Inspect again before applying changes.")
    return snapshot


@tool("verify_sheet_metal_part", "Read-only: verify sheet-metal parameters and folded bounding-box dimensions. Lengths and tolerance are mm.",
      {"thickness_mm": {"type": "number", "exclusiveMinimum": 0},
       "inside_radius_mm": {"type": "number", "minimum": 0},
       "expected_size_mm": {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "number"}},
       "expected_body_count": {"type": "integer", "minimum": 1},
       "minimum_volume_mm3": {"type": "number", "exclusiveMinimum": 0},
       "require_folded": {"type": "boolean", "default": True},
       "expected_feature_states": {"type": "object", "additionalProperties": {"type": "boolean"}},
       "tolerance_mm": {"type": "number", "minimum": 0, "default": 0.05}})
def verify_sheet_metal_part(args: dict[str, Any]) -> dict[str, Any]:
    snapshot = _snapshot()
    checks: list[dict[str, Any]] = []
    parameters = snapshot["parameters"]
    tolerance = float(args.get("tolerance_mm", 0.05))
    if "thickness_mm" in args:
        expected = _finite_positive(args["thickness_mm"], "thickness_mm")
        checks.append({"name": "thickness", "ok": bool(parameters) and all(math.isclose(p["thickness_mm"], expected, abs_tol=tolerance) for p in parameters)})
    if "inside_radius_mm" in args:
        expected = float(args["inside_radius_mm"])
        checks.append({"name": "inside_radius", "ok": bool(parameters) and all(math.isclose(p["bend_radius_mm"], expected, abs_tol=tolerance) for p in parameters)})
    if args.get("expected_size_mm"):
        actual = sorted(float(x) for x in (snapshot.get("bounding_box") or {}).get("size_mm", []))
        expected = sorted(float(x) for x in args["expected_size_mm"])
        checks.append({"name": "bounding_box", "ok": len(actual) >= len(expected) and all(math.isclose(a, e, abs_tol=tolerance) for a, e in zip(actual[-len(expected):], expected)), "actual_mm": actual})
    expected_bodies = int(args.get("expected_body_count", 1))
    checks.append({"name": "sheet_metal_body_count", "ok": snapshot["sheet_metal_body_count"] == expected_bodies,
                   "actual": snapshot["sheet_metal_body_count"], "expected": expected_bodies})
    if "minimum_volume_mm3" in args:
        minimum = _finite_positive(args["minimum_volume_mm3"], "minimum_volume_mm3")
        actual_volume = float((snapshot.get("mass_properties") or {}).get("volume_mm3", 0))
        checks.append({"name": "volume_sanity", "ok": actual_volume >= minimum,
                       "actual_mm3": actual_volume, "minimum_mm3": minimum})
    if bool(args.get("require_folded", True)):
        checks.append({"name": "folded_state", "ok": snapshot["folded_state"]})
    states = {item["feature"]: item["suppressed"] for item in snapshot["flat_patterns"]}
    for name, suppressed in dict(args.get("expected_feature_states", {})).items():
        checks.append({"name": f"feature_state:{name}", "ok": states.get(name) is bool(suppressed),
                       "actual_suppressed": states.get(name), "expected_suppressed": bool(suppressed)})
    checks.extend([{"name": "volume_available", "ok": float((snapshot.get("mass_properties") or {}).get("volume_mm3", 0)) > 0},
                   {"name": "persistent_feature_references", "ok": all(item["persistent_reference"] for item in snapshot["features"])},
                   {"name": "rebuild", "ok": not snapshot["problems"]}])
    ok = all(check["ok"] for check in checks)
    return result(ok, "Sheet-metal verification passed." if ok else "Sheet-metal verification failed.", checks=checks, snapshot=snapshot)


PLATE_SCHEMA = {
    "profile": {"type": "string", "enum": ["standard_2026"], "default": "standard_2026"},
    "width_mm": {"type": "number", "exclusiveMinimum": 0},
    "height_mm": {"type": "number", "exclusiveMinimum": 0},
    "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
    "inside_radius_mm": {"type": "number", "minimum": 0},
    "dimension_mode": {"type": "string", "enum": DIMENSION_MODES},
    "name": {"type": "string", "default": "Plate"},
}


@tool("create_sheet_metal_plate", "Create a new unsaved rectangular sheet-metal part from a configured profile and verify native parameters and bounds. Does not save or close documents.", PLATE_SCHEMA,
      ["width_mm", "height_mm", "thickness_mm", "inside_radius_mm", "dimension_mode"])
def create_sheet_metal_plate(args: dict[str, Any]) -> dict[str, Any]:
    width = _finite_positive(args["width_mm"], "width_mm")
    height = _finite_positive(args["height_mm"], "height_mm")
    thickness = _finite_positive(args["thickness_mm"], "thickness_mm")
    radius = float(args["inside_radius_mm"])
    if not math.isfinite(radius) or radius < 0:
        raise RuntimeError("inside_radius_mm must be finite and nonnegative.")
    mode = str(args["dimension_mode"])
    if mode not in DIMENSION_MODES:
        raise RuntimeError("dimension_mode must be finished_outer or flat_blank.")
    template = _resolve_template()
    if template is None:
        return result(False, f"The standard_2026 profile could not resolve the '{PROFILE['template_label']}' part template. Set {PROFILE_ENV} to its .prtdot path.")
    app = running_app()
    doc = app.NewDocument(str(template), 0, 0.0, 0.0)
    if doc is None:
        return result(False, "SOLIDWORKS could not create a part from the configured template.")
    sketch_name = str(args.get("name", "Plate"))
    opened = sw_sketch.create_sketch({"plane": PROFILE["preferred_plane"], "name": sketch_name})
    if not opened.get("ok"):
        return result(False, "The template opened, but the plate sketch could not be created; the new unsaved document was left open.", sketch=opened)
    drawn = sw_sketch.draw_rectangle({"x1_mm": 0, "y1_mm": 0, "x2_mm": width, "y2_mm": height})
    closed = sw_sketch.close_sketch({})
    if not drawn.get("ok") or not closed.get("ok"):
        return result(False, "The plate sketch was not created and closed cleanly; the new unsaved document was left open.", sketch=drawn)
    created = sw_sheetmetal.sheet_metal_base_flange({"sketch_name": str(args.get("name", "Plate")),
        "thickness_mm": thickness, "bend_radius_mm": radius, "k_factor": 0.5})
    if not created.get("ok"):
        return result(False, "The new document was created but its base flange failed; it remains open and unsaved.", base_flange=created)
    verified = verify_sheet_metal_part({"thickness_mm": thickness, "inside_radius_mm": radius,
                                        "expected_size_mm": [width, height], "tolerance_mm": 0.05})
    return result(bool(verified.get("ok")), "Created and verified an unsaved sheet-metal plate." if verified.get("ok") else "Created the plate but verification failed; it remains open and unsaved.",
                  dimension_mode=mode, verification=verified.get("data", {}), snapshot=_snapshot())


SIDE_SCHEMA = {"type": "string", "enum": ["left", "right", "bottom", "top"]}
PANEL_SCHEMA = {**PLATE_SCHEMA,
    "flange_sides": {"type": "array", "minItems": 1, "uniqueItems": True,
                      "items": SIDE_SCHEMA},
    "flange_height_mm": {"type": "number", "exclusiveMinimum": 0},
    "flange_angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180, "default": 90},
    "flange_position": {"type": "string", "enum": list(sw_sheetmetal.FLANGE_POSITIONS), "default": "material_inside"},
    "corner_gap_mm": {"type": "number", "minimum": 0, "default": 0},
    "edge_flanges": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "object", "properties": {
        "side": SIDE_SCHEMA, "height_mm": {"type": "number", "exclusiveMinimum": 0},
        "angle_degrees": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180},
        "position": {"type": "string", "enum": list(sw_sheetmetal.FLANGE_POSITIONS)},
        "corner_gap_mm": {"type": "number", "minimum": 0}}, "required": ["side", "height_mm"]}},
    "hems": {"type": "array", "items": {"type": "object", "properties": {
        "side": SIDE_SCHEMA, "hem_type": {"type": "string", "enum": list(sw_sheetmetal.HEM_TYPES)},
        "position": {"type": "string", "enum": list(sw_sheetmetal.HEM_POSITIONS)},
        "length_mm": {"type": "number", "exclusiveMinimum": 0}, "gap_mm": {"type": "number", "minimum": 0},
        "radius_mm": {"type": "number", "minimum": 0}}, "required": ["side", "hem_type", "length_mm"]}},
    "break_corners": {"type": "array", "items": {"type": "object", "properties": {
        "side": SIDE_SCHEMA, "corner_type": {"type": "string", "enum": ["chamfer", "fillet"]},
        "size_mm": {"type": "number", "exclusiveMinimum": 0}}, "required": ["side", "corner_type", "size_mm"]}},
    "closed_corners": {"type": "array", "items": {"type": "object", "properties": {
        "extend_side": SIDE_SCHEMA, "match_side": SIDE_SCHEMA,
        "corner_type": {"type": "string", "enum": list(sw_sheetmetal.CLOSED_CORNER_TYPES)},
        "gap_mm": {"type": "number", "minimum": 0}, "open_bend_region": {"type": "boolean"},
        "overlap_ratio": {"type": "number", "minimum": 0, "maximum": 1}},
        "required": ["extend_side", "match_side"]}},
    "corner_reliefs": {"type": "array", "items": {"type": "object", "properties": {
        "side_a": SIDE_SCHEMA, "side_b": SIDE_SCHEMA,
        "relief_type": {"type": "string", "enum": list(sw_sheetmetal.CORNER_RELIEF_TYPES)},
        "relief_size_mm": {"type": "number", "exclusiveMinimum": 0},
        "break_type": {"type": "string", "enum": ["chamfer", "fillet"]},
        "break_distance_mm": {"type": "number", "minimum": 0}},
        "required": ["side_a", "side_b", "relief_type", "relief_size_mm"]}},
}


def _rectangle_side_edges(width: float, height: float, sides: list[str], tolerance: float = .01) -> list[int]:
    _, doc = active_document()
    candidates = enumerate_edges(doc)
    matched: list[int] = []
    for side in sides:
        options = []
        for edge in candidates:
            start, end = edge.get("start_mm"), edge.get("end_mm")
            if edge.get("curve_type") != "line" or not start or not end:
                continue
            if side == "left":
                correct = abs(start[0]) <= tolerance and abs(end[0]) <= tolerance and float(edge.get("length_mm", 0)) > tolerance
            elif side == "right":
                correct = abs(start[0]-width) <= tolerance and abs(end[0]-width) <= tolerance and float(edge.get("length_mm", 0)) > tolerance
            elif side == "bottom":
                correct = abs(start[1]) <= tolerance and abs(end[1]) <= tolerance and float(edge.get("length_mm", 0)) > tolerance
            else:
                correct = abs(start[1]-height) <= tolerance and abs(end[1]-height) <= tolerance and float(edge.get("length_mm", 0)) > tolerance
            if correct:
                options.append(edge)
        if not options:
            raise RuntimeError(f"Could not resolve a unique rectangular base edge for side '{side}'.")
        # Adjacent flanges can shorten an original base edge. Prefer the longest
        # remaining collinear boundary, then the upper thickness edge.
        chosen = max(options, key=lambda edge: (float(edge.get("length_mm", 0)),
            (edge["start_mm"][2] + edge["end_mm"][2]) / 2))
        matched.append(int(chosen["index"]))
    if len(set(matched)) != len(sides):
        raise RuntimeError("Two requested panel sides resolved to the same native edge.")
    return matched


def _feature_topology_indices(doc: Any, feature_name: str) -> tuple[list[int], list[int]]:
    feature = find_feature(doc, feature_name)
    if feature is None:
        raise RuntimeError(f"The native feature '{feature_name}' disappeared; topology is ambiguous.")
    feature_faces = as_list(safe(feature, "GetFaces"))
    face_refs = {persistent_reference_id(doc, face) for face in feature_faces}
    edge_refs = {persistent_reference_id(doc, edge) for face in feature_faces
                 for edge in as_list(safe(face, "GetEdges"))}
    faces = [int(entry["index"]) for entry in enumerate_faces(doc)
             if persistent_reference_id(doc, entry["_obj"]) in face_refs]
    edges = [int(entry["index"]) for entry in enumerate_edges(doc)
             if persistent_reference_id(doc, entry["_obj"]) in edge_refs]
    if not faces or not edges:
        raise RuntimeError(f"Could not resolve stable topology owned by '{feature_name}'.")
    return faces, edges


def _outer_edge_for_flange(doc: Any, feature_name: str) -> int:
    _, edge_indices = _feature_topology_indices(doc, feature_name)
    by_index = {int(entry["index"]): entry for entry in enumerate_edges(doc)}
    lines = [by_index[index] for index in edge_indices if by_index[index].get("curve_type") == "line"]
    if not lines:
        raise RuntimeError(f"The flange '{feature_name}' has no resolvable straight outer edge.")
    def score(edge: dict[str, Any]) -> tuple[float, float]:
        start, end = edge.get("start_mm", [0, 0, 0]), edge.get("end_mm", [0, 0, 0])
        return (abs((start[2] + end[2]) / 2), float(edge.get("length_mm", 0)))
    return int(max(lines, key=score)["index"])


def _wall_face_for_flange(doc: Any, feature_name: str) -> int:
    face_indices, _ = _feature_topology_indices(doc, feature_name)
    by_index = {int(entry["index"]): entry for entry in enumerate_faces(doc)}
    planar = [by_index[index] for index in face_indices if by_index[index].get("surface_type") == "plane"]
    if not planar:
        raise RuntimeError(f"The flange '{feature_name}' has no resolvable planar wall face.")
    return int(max(planar, key=lambda entry: float(entry.get("area_mm2", 0)))["index"])


def _panel_flange_declarations(args: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = args.get("edge_flanges")
    if explicit:
        declarations = [dict(item) for item in explicit]
    else:
        sides = [str(side) for side in args.get("flange_sides", [])]
        if not sides or args.get("flange_height_mm") is None:
            raise RuntimeError("Provide edge_flanges, or both legacy flange_sides and flange_height_mm.")
        declarations = [{"side": side, "height_mm": args["flange_height_mm"],
                         "angle_degrees": args.get("flange_angle_degrees", 90),
                         "position": args.get("flange_position", "material_inside"),
                         "corner_gap_mm": args.get("corner_gap_mm", 0)} for side in sides]
    sides = [str(item["side"]) for item in declarations]
    if len(set(sides)) != len(sides):
        raise RuntimeError("Each declarative panel side may have only one edge flange.")
    for item in declarations:
        if str(item["side"]) not in {"left", "right", "bottom", "top"}:
            raise RuntimeError(f"Unsupported panel side '{item['side']}'.")
        _finite_positive(item["height_mm"], "edge_flanges.height_mm")
        angle = float(item.get("angle_degrees", 90)); gap = float(item.get("corner_gap_mm", 0))
        if not math.isfinite(angle) or not 0 < angle < 180:
            raise RuntimeError("edge_flanges.angle_degrees must be finite and between 0 and 180.")
        if not math.isfinite(gap) or gap < 0:
            raise RuntimeError("edge_flanges.corner_gap_mm must be finite and nonnegative.")
        if str(item.get("position", "material_inside")) not in sw_sheetmetal.FLANGE_POSITIONS:
            raise RuntimeError("edge_flanges.position is unsupported.")
    return declarations


def _validate_panel_post_features(args: dict[str, Any], declared_sides: set[str]) -> None:
    def require_side(side: Any, label: str) -> str:
        name = str(side)
        if name not in declared_sides:
            raise RuntimeError(f"{label} side '{name}' has no declared edge flange.")
        return name
    for item in args.get("hems", []):
        require_side(item["side"], "Hem")
        _finite_positive(item["length_mm"], "hems.length_mm")
        if str(item["hem_type"]) not in sw_sheetmetal.HEM_TYPES:
            raise RuntimeError("hems.hem_type is unsupported.")
        for key in ("gap_mm", "radius_mm"):
            number = float(item.get(key, 0))
            if not math.isfinite(number) or number < 0:
                raise RuntimeError(f"hems.{key} must be finite and nonnegative.")
    for item in args.get("break_corners", []):
        require_side(item["side"], "Break-corner")
        _finite_positive(item["size_mm"], "break_corners.size_mm")
        if str(item["corner_type"]) not in {"chamfer", "fillet"}:
            raise RuntimeError("break_corners.corner_type is unsupported.")
    for collection, first_key, second_key in (("closed_corners", "extend_side", "match_side"),
                                               ("corner_reliefs", "side_a", "side_b")):
        for item in args.get(collection, []):
            first = require_side(item[first_key], collection)
            second = require_side(item[second_key], collection)
            if first == second or {first, second} in ({"left", "right"}, {"bottom", "top"}):
                raise RuntimeError(f"{collection} must reference two distinct adjacent flange sides.")
    for item in args.get("closed_corners", []):
        gap = float(item.get("gap_mm", 0)); ratio = float(item.get("overlap_ratio", .5))
        if not math.isfinite(gap) or gap < 0 or not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise RuntimeError("closed_corners gap/overlap values are invalid.")
    for item in args.get("corner_reliefs", []):
        _finite_positive(item["relief_size_mm"], "corner_reliefs.relief_size_mm")
        distance = float(item.get("break_distance_mm", 0))
        if not math.isfinite(distance) or distance < 0:
            raise RuntimeError("corner_reliefs.break_distance_mm must be finite and nonnegative.")


@tool("create_sheet_metal_panel", "Create an unsaved rectangular sheet-metal panel/tray with declarative edge flanges, hems, break/closed corners and corner reliefs. All targets use semantic panel sides and native readback; does not save or invoke PDM.", PANEL_SCHEMA,
      ["width_mm", "height_mm", "thickness_mm", "inside_radius_mm", "dimension_mode"])
def create_sheet_metal_panel(args: dict[str, Any]) -> dict[str, Any]:
    declarations = _panel_flange_declarations(args)
    _validate_panel_post_features(args, {str(item["side"]) for item in declarations})
    payload = create_sheet_metal_plate(args)
    if not payload.get("ok"):
        return payload
    width = float(args["width_mm"]); height = float(args["height_mm"])
    operations: list[dict[str, Any]] = []
    feature_by_side: dict[str, str] = {}
    for declaration in declarations:
        side = str(declaration["side"])
        edge_index = _rectangle_side_edges(width, height, [side])[0]
        feature_name = f"PanelFlange_{side}"
        flange = sw_sheetmetal.edge_flange({"selection": {"edges": [edge_index]},
            "height_mm": float(declaration["height_mm"]),
            "angle_degrees": float(declaration.get("angle_degrees", 90)),
            "position_type": str(declaration.get("position", "material_inside")),
            "corner_gap_mm": float(declaration.get("corner_gap_mm", 0)), "name": feature_name})
        operations.append({"kind": "edge_flange", "side": side, "result": flange})
        if not flange.get("ok"):
            return result(False, "The panel remains open and unsaved, but a declarative edge flange failed.",
                          operations=operations, side=side, resolved_edge_index=edge_index)
        feature_by_side[side] = feature_name
    _, doc = active_document()
    for index, declaration in enumerate(args.get("hems", [])):
        side = str(declaration["side"]); feature_name = feature_by_side.get(side)
        if not feature_name:
            raise RuntimeError(f"Hem side '{side}' has no declared edge flange.")
        edge_index = _outer_edge_for_flange(doc, feature_name)
        native_args = {**declaration, "selection": {"edges": [edge_index]}, "name": f"PanelHem_{side}_{index}"}
        native_args.pop("side", None)
        outcome = sw_sheetmetal.sheet_metal_hem(native_args)
        operations.append({"kind": "hem", "side": side, "result": outcome})
        if not outcome.get("ok"):
            return result(False, "The panel remains open and unsaved, but a declarative hem failed.", operations=operations)
    for index, declaration in enumerate(args.get("break_corners", [])):
        side = str(declaration["side"]); feature_name = feature_by_side.get(side)
        if not feature_name:
            raise RuntimeError(f"Break-corner side '{side}' has no declared edge flange.")
        edge_index = _outer_edge_for_flange(doc, feature_name)
        outcome = sw_sheetmetal.sheet_metal_break_corner({"selection": {"edges": [edge_index]},
            "corner_type": declaration["corner_type"], "size_mm": declaration["size_mm"],
            "name": f"PanelBreakCorner_{side}_{index}"})
        operations.append({"kind": "break_corner", "side": side, "result": outcome})
        if not outcome.get("ok"):
            return result(False, "The panel remains open and unsaved, but a declarative break corner failed.", operations=operations)
    for index, declaration in enumerate(args.get("closed_corners", [])):
        extend, match = str(declaration["extend_side"]), str(declaration["match_side"])
        if extend not in feature_by_side or match not in feature_by_side or extend == match:
            raise RuntimeError("Closed-corner sides must name two distinct declared edge flanges.")
        native_args = {**declaration,
            "faces_to_extend": [_wall_face_for_flange(doc, feature_by_side[extend])],
            "faces_to_match": [_wall_face_for_flange(doc, feature_by_side[match])],
            "name": f"PanelClosedCorner_{extend}_{match}_{index}"}
        native_args.pop("extend_side"); native_args.pop("match_side")
        outcome = sw_sheetmetal.sheet_metal_closed_corner(native_args)
        operations.append({"kind": "closed_corner", "sides": [extend, match], "result": outcome})
        if not outcome.get("ok"):
            return result(False, "The panel remains open and unsaved, but a declarative closed corner failed.", operations=operations)
    for index, declaration in enumerate(args.get("corner_reliefs", [])):
        side_a, side_b = str(declaration["side_a"]), str(declaration["side_b"])
        if side_a not in feature_by_side or side_b not in feature_by_side or side_a == side_b:
            raise RuntimeError("Corner-relief sides must name two distinct declared edge flanges.")
        native_args = {**declaration, "selection": {"faces": [
            _wall_face_for_flange(doc, feature_by_side[side_a]),
            _wall_face_for_flange(doc, feature_by_side[side_b])]},
            "name": f"PanelCornerRelief_{side_a}_{side_b}_{index}"}
        native_args.pop("side_a"); native_args.pop("side_b")
        outcome = sw_sheetmetal.sheet_metal_corner_relief(native_args)
        operations.append({"kind": "corner_relief", "sides": [side_a, side_b], "result": outcome})
        if not outcome.get("ok"):
            return result(False, "The panel remains open and unsaved, but a declarative corner relief failed.", operations=operations)
    snapshot = _snapshot()
    return result(not snapshot["problems"], "Created and verified an unsaved sheet-metal panel/tray.",
                  operations=operations, sides=list(feature_by_side), snapshot=snapshot)


def _unit_direction(start: list[float], end: list[float]) -> list[float] | None:
    delta = [end[index] - start[index] for index in range(3)]
    length = math.sqrt(sum(component * component for component in delta))
    return [round(component / length, 9) for component in delta] if length > 1e-12 else None


def _point_line_gap(point: list[float], origin: list[float], direction: list[float]) -> float:
    offset = [point[index] - origin[index] for index in range(3)]
    projection = sum(offset[index] * direction[index] for index in range(3))
    normal = [offset[index] - projection * direction[index] for index in range(3)]
    return math.sqrt(sum(component * component for component in normal))


def _relation_summaries(segment: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    try:
        relations = as_list(value(segment, "GetRelations"))
    except Exception:
        relations = []
    for relation in relations:
        try:
            summaries.append({"type": int(value(relation, "GetRelationType")),
                              "suppressed": bool(value(relation, "Suppressed"))})
        except Exception:
            summaries.append({"type": "unknown"})
    return summaries


@tool("inspect_sketch_alignment", "Read-only: inspect a named sketch's segments and the active part's straight model edges before adding a guarded relation.",
      {"sketch_name": {"type": "string"}}, ["sketch_name"])
def inspect_sketch_alignment(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    name = str(args["sketch_name"])
    listed = sw_sketch.list_sketch_segments({"sketch_name": name})
    if not listed.get("ok"):
        return listed
    segments = listed.get("data", {}).get("segments", [])
    edges = [entry for entry in enumerate_edges(doc) if entry.get("curve_type") == "line"]
    native_segments = sketch_segment_objects(doc, name)
    native_edges = iter_edge_objects(doc)
    segment_refs = {index: persistent_reference_id(doc, segment).hex()
                    for index, segment in enumerate(native_segments)}
    edge_refs = {index: persistent_reference_id(doc, edge).hex()
                 for index, (edge, _matrix) in enumerate(native_edges)}
    _, sketch_feature = resolve_sketch(doc, name)
    sketch = value(sketch_feature, "GetSpecificFeature2")
    sketch_to_model = value(value(value(sketch, "ModelToSketchTransform"), "Inverse"), "ArrayData")
    for entry in segments:
        entry["persistent_reference"] = segment_refs.get(int(entry["index"]), "")
        if entry.get("type") == "line" and "start_mm" in entry and "end_mm" in entry:
            start = apply_transform([coordinate / 1000 for coordinate in entry["start_mm"]], sketch_to_model)
            end = apply_transform([coordinate / 1000 for coordinate in entry["end_mm"]], sketch_to_model)
            entry["model_start_mm"] = [round(coordinate * 1000, 6) for coordinate in start]
            entry["model_end_mm"] = [round(coordinate * 1000, 6) for coordinate in end]
            entry["model_direction"] = _unit_direction(start, end)
            entry["existing_relations"] = _relation_summaries(native_segments[int(entry["index"])])
    for entry in edges:
        entry["persistent_reference"] = edge_refs.get(int(entry["index"]), "")
        entry.pop("_obj", None); entry.pop("_point_m", None)
    compatible: list[dict[str, Any]] = []
    for segment in segments:
        segment_direction = segment.get("model_direction")
        if not segment_direction:
            continue
        segment_start = [coordinate / 1000 for coordinate in segment["model_start_mm"]]
        for edge in edges:
            if "start_mm" not in edge or "end_mm" not in edge:
                continue
            edge_start = [coordinate / 1000 for coordinate in edge["start_mm"]]
            edge_end = [coordinate / 1000 for coordinate in edge["end_mm"]]
            edge_direction = _unit_direction(edge_start, edge_end)
            if not edge_direction:
                continue
            parallel_error = 1.0 - abs(sum(segment_direction[i] * edge_direction[i] for i in range(3)))
            if parallel_error <= 1e-6:
                compatible.append({"sketch_segment_index": segment["index"], "edge_index": edge["index"],
                                   "direction_error": round(parallel_error, 9),
                                   "gap_mm": round(_point_line_gap(segment_start, edge_start, edge_direction) * 1000, 6),
                                   "sketch_segment_reference": segment["persistent_reference"],
                                   "model_edge_reference": edge["persistent_reference"]})
    snapshot = _snapshot()
    return result(True, "Inspected sketch segments and compatible straight model edges.",
                  sketch=name, sketch_segments=segments, model_edges=edges,
                  compatible_pairs=compatible,
                  edit_token=_token(snapshot))


@tool("set_sketch_line_collinear_to_edge", "Guarded edit: add a direct native collinear relation between one sketch line and one straight model edge. Requires a fresh token from inspect_sketch_alignment. Does not save.",
      {"sketch_name": {"type": "string"}, "sketch_segment_index": {"type": "integer", "minimum": 0},
       "edge_index": {"type": "integer", "minimum": 0},
       "sketch_segment_reference": {"type": "string", "minLength": 1},
       "model_edge_reference": {"type": "string", "minLength": 1},
       "edit_token": {"type": "string"}},
      ["sketch_name", "sketch_segment_index", "edge_index", "sketch_segment_reference",
       "model_edge_reference", "edit_token"])
def set_sketch_line_collinear_to_edge(args: dict[str, Any]) -> dict[str, Any]:
    require_edit_token(args["edit_token"])
    _, doc = active_document()
    name = str(args["sketch_name"])
    segment_index = int(args["sketch_segment_index"])
    edge_index = int(args["edge_index"])
    segments = sketch_segment_objects(doc, name)
    edges = iter_edge_objects(doc)
    if not 0 <= segment_index < len(segments):
        raise RuntimeError(f"Sketch segment index {segment_index} is out of range.")
    if not 0 <= edge_index < len(edges):
        raise RuntimeError(f"Edge index {edge_index} is out of range.")
    segment, edge = segments[segment_index], edges[edge_index][0]
    segment_ref = persistent_reference_id(doc, segment)
    edge_ref = persistent_reference_id(doc, edge)
    if segment_ref.hex() != str(args["sketch_segment_reference"]) or edge_ref.hex() != str(args["model_edge_reference"]):
        raise RuntimeError("The inspected sketch segment or model edge persistent reference changed; inspect again.")
    opened = sw_sketch.edit_sketch({"sketch_name": name})
    if not opened.get("ok"):
        return opened
    sketch = doc.SketchManager.ActiveSketch
    manager = value(sketch, "RelationManager")
    flag_methods(manager, "AddRelation", "GetRelationsCount")
    before = int(manager.GetRelationsCount(0))
    try:
        manager.AddRelation(dispatch_array([segment, edge]), 27)  # swConstraintType_COLINEAR
    except Exception as exc:
        sw_sketch.close_sketch({})
        clear_selection(doc)
        return result(False, f"SOLIDWORKS rejected the direct collinear relation: {exc}")
    added = int(manager.GetRelationsCount(0)) - before
    sw_sketch.close_sketch({})
    sw_feature.set_rollback_bar({"position": "end"})
    rebuild(doc)
    clear_selection(doc)
    current_segments = sketch_segment_objects(doc, name)
    current_edges = iter_edge_objects(doc)
    stable = (segment_index < len(current_segments) and edge_index < len(current_edges)
              and persistent_reference_id(doc, current_segments[segment_index]) == segment_ref
              and persistent_reference_id(doc, current_edges[edge_index][0]) == edge_ref)
    problems = whats_wrong(doc)
    ok = added > 0 and stable and not problems
    return result(ok, "Added and verified the direct collinear relation." if ok else
                  "The relation was not verified after rebuilding; no converted geometry was created.",
                  relations_added=added, references_stable=stable, problems=problems,
                  snapshot=_snapshot())
