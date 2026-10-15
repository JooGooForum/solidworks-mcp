# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Native feature boundary checks; geometry acceptance stays in live tests."""

from pathlib import Path
from types import SimpleNamespace
import math
import tempfile
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp import sw_core, sw_multibody, sw_sheetmetal, sw_weldment


class SheetMetalBoundaryTests(unittest.TestCase):
    def test_base_flange_schema_keeps_explicit_mode_backward_compatible(self):
        schema = next(tool.inputSchema for tool in sw_core.TOOLS if tool.name == "sheet_metal_base_flange")
        self.assertIn("thickness_mm", schema["properties"])
        self.assertIn("use_document_defaults", schema["properties"])
        self.assertFalse(schema["properties"]["use_document_defaults"]["default"])

    def test_edge_flange_schema_exposes_native_controls(self):
        schema = next(tool.inputSchema for tool in sw_core.TOOLS if tool.name == "edge_flange")
        self.assertEqual(schema["required"], ["selection", "height_mm"])
        self.assertEqual(schema["properties"]["position_type"]["default"], "material_inside")
        self.assertEqual(schema["properties"]["angle_degrees"]["default"], 90)

    def test_invalid_sheet_parameters_are_rejected_before_com(self):
        for args in ({"thickness_mm": 0}, {"thickness_mm": 1, "bend_radius_mm": -1},
                     {"thickness_mm": 1, "k_factor": 1.1}, {"thickness_mm": 1, "k_factor": float("nan")}):
            with self.subTest(args=args), patch.object(sw_sheetmetal, "require_part") as require:
                with self.assertRaises(RuntimeError):
                    sw_sheetmetal.sheet_metal_base_flange(args)
                require.assert_not_called()

    def test_empty_parameter_update_cannot_roll_back_the_model(self):
        with patch.object(sw_sheetmetal, "require_part") as require:
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.set_sheet_metal_parameters({})
            require.assert_not_called()

    def test_document_defaults_reject_explicit_sheet_metal_overrides(self):
        for key, raw in (("thickness_mm", 3), ("bend_radius_mm", 2), ("k_factor", 0.4)):
            with self.subTest(key=key), patch.object(sw_sheetmetal, "require_part") as require:
                with self.assertRaises(RuntimeError):
                    sw_sheetmetal.sheet_metal_base_flange({"use_document_defaults": True, key: raw})
                require.assert_not_called()

    def test_parameter_readback_reports_gauge_and_default_relationship(self):
        definition = SimpleNamespace(Thickness=0.003, BendRadius=0.002, KFactor=0.4,
                                     UseGaugeTable=True, UseMaterialSheetMetalParameters=True,
                                     UseDefaultBendAllowance=True, OverrideDefaultSheetMetalParameters=False,
                                     GaugeTablePath=r"C:\gauges\plate.xlsx", ThicknessTableName="3 mm")
        feature = SimpleNamespace(Name="Sheet-Metal1", GetDefinition=lambda: definition)
        actual = sw_sheetmetal._read_parameters(feature)
        self.assertEqual(actual["thickness_mm"], 3)
        self.assertEqual(actual["bend_radius_mm"], 2)
        self.assertTrue(actual["use_gauge_table"])
        self.assertTrue(actual["use_material_sheet_metal_parameters"])
        self.assertEqual(actual["allowance_source"], "document_default")

    def test_multi_edge_flange_readback_converts_native_units(self):
        definition = SimpleNamespace(GetEdgeCount=lambda: 4, OffsetDistance=0.1, BendAngle=math.pi / 2,
                                     PositionType=1, GapDistance=0.001, UseDefaultBendRadius=True,
                                     UseDefaultBendAllowance=True, UseDefaultBendRelief=True,
                                     UsePositionTrimSideBends=True)
        feature = SimpleNamespace(Name="Tray walls", GetDefinition=lambda: definition)
        actual = sw_sheetmetal._read_edge_flange(feature)
        self.assertEqual(actual["selected_edge_count"], 4)
        self.assertAlmostEqual(actual["height_mm"], 100)
        self.assertAlmostEqual(actual["angle_degrees"], 90)
        self.assertEqual(actual["position_type"], "material_inside")
        self.assertAlmostEqual(actual["corner_gap_mm"], 1)

    def test_edge_flange_validation_happens_before_com(self):
        for args in ({"selection": {"edges": [0]}, "height_mm": 0},
                     {"selection": {"edges": [0]}, "height_mm": 10, "angle_degrees": 180},
                     {"selection": {"edges": [0]}, "height_mm": 10, "corner_gap_mm": -1}):
            with self.subTest(args=args), patch.object(sw_sheetmetal, "require_part") as require:
                with self.assertRaises(RuntimeError):
                    sw_sheetmetal.edge_flange(args)
                require.assert_not_called()

    def test_hem_schema_exposes_native_controls(self):
        schema = next(tool.inputSchema for tool in sw_core.TOOLS if tool.name == "sheet_metal_hem")
        self.assertEqual(schema["required"], ["selection", "length_mm"])
        self.assertEqual(schema["properties"]["hem_type"]["enum"], ["open", "closed", "teardrop", "rolled"])

    def test_hem_and_break_corner_validate_before_com(self):
        with patch.object(sw_sheetmetal, "require_part") as require:
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.sheet_metal_hem({"selection": {"edges": [0]}, "length_mm": 0})
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.sheet_metal_break_corner({"selection": {"edges": [0]}, "corner_type": "chamfer", "size_mm": 0})
            require.assert_not_called()

    def test_break_corner_definition_readback_uses_native_distance_and_entities(self):
        definition = SimpleNamespace(Distance=.002, Type=1, GetEntitiesCount=lambda: 2,
                                     AccessSelections=lambda doc, component: True,
                                     ReleaseSelectionAccess=Mock())
        feature = SimpleNamespace(Name="Break-Corner1", GetTypeName2=lambda: "BreakCorner",
                                  GetDefinition=lambda: definition)
        actual = sw_sheetmetal._read_break_corner(feature, object())
        self.assertEqual(actual["distance_mm"], 2)
        self.assertEqual(actual["entity_count"], 2)
        self.assertEqual(actual["corner_type_code"], 1)
        definition.ReleaseSelectionAccess.assert_called_once()

    def test_corner_and_jog_schemas_expose_native_controls(self):
        schemas = {tool.name: tool.inputSchema for tool in sw_core.TOOLS}
        self.assertEqual(schemas["sheet_metal_corner_relief"]["required"],
                         ["selection", "relief_type", "relief_size_mm"])
        self.assertEqual(schemas["sheet_metal_closed_corner"]["properties"]["corner_type"]["enum"],
                         ["butt", "overlap", "underlap"])
        self.assertEqual(schemas["sheet_metal_jog"]["properties"]["dimension_position"]["enum"],
                         ["inside_offset", "outside_offset", "overall"])

    def test_corner_and_jog_validation_happens_before_com(self):
        cases = (
            (sw_sheetmetal.sheet_metal_corner_relief,
             {"selection": {"edges": [0]}, "relief_type": "circular", "relief_size_mm": 0}),
            (sw_sheetmetal.sheet_metal_closed_corner,
             {"faces_to_extend": [0], "faces_to_match": [1], "gap_mm": -1}),
            (sw_sheetmetal.sheet_metal_jog,
             {"selection": {"faces": [0]}, "angle_degrees": 180, "radius_mm": 1, "offset_mm": 5}),
        )
        for function, args in cases:
            with self.subTest(function=function.__name__), patch.object(sw_sheetmetal, "require_part") as require:
                with self.assertRaises(RuntimeError):
                    function(args)
                require.assert_not_called()

    def test_rip_sketched_bend_and_fold_schemas_are_explicit(self):
        schemas = {tool.name: tool.inputSchema for tool in sw_core.TOOLS}
        self.assertEqual(schemas["sheet_metal_rip"]["properties"]["direction"]["enum"],
                         ["current", "other", "both"])
        self.assertEqual(schemas["sheet_metal_sketched_bend"]["required"],
                         ["sketch_name", "angle_degrees"])
        self.assertEqual(schemas["sheet_metal_unfold"]["required"], ["fixed_face_index"])
        self.assertEqual(schemas["sheet_metal_fold"]["required"],
                         ["fixed_face_index", "unfold_feature_name"])

    def test_rip_and_sketched_bend_validate_before_com(self):
        with patch.object(sw_sheetmetal, "require_part") as require:
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.sheet_metal_rip({"selection": {"edges": [0]}, "gap_mm": 0})
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.sheet_metal_sketched_bend({"sketch_name": "Bend", "angle_degrees": 180})
            require.assert_not_called()

    def test_rip_definition_readback_uses_native_gap_edges_and_directions(self):
        edges = [object(), object()]
        definition = SimpleNamespace(Gap=.0015, Edges=edges, GetEdgesCount=lambda: 2,
                                     GetDirection=lambda edge: edges.index(edge) + 1,
                                     AccessSelections=lambda doc, component: True,
                                     ReleaseSelectionAccess=Mock())
        feature = SimpleNamespace(Name="Rip1", GetTypeName2=lambda: "Rip", GetDefinition=lambda: definition)
        actual = sw_sheetmetal._read_rip(feature, object())
        self.assertEqual(actual["gap_mm"], 1.5)
        self.assertEqual(actual["edge_count"], 2)
        self.assertEqual(actual["direction_codes"], [1, 2])
        definition.ReleaseSelectionAccess.assert_called_once()

    def test_unfold_requires_explicit_bends_before_selection(self):
        doc = object()
        with patch.object(sw_sheetmetal, "require_part", return_value=(None, doc)), \
                patch.object(sw_sheetmetal, "iter_feature_objects", return_value=[]), \
                patch.object(sw_sheetmetal, "apply_selection") as select:
            with self.assertRaisesRegex(RuntimeError, "bend_feature_names"):
                sw_sheetmetal.sheet_metal_unfold({"fixed_face_index": 0})
            select.assert_not_called()

    def test_normal_cut_schema_defaults_to_through_all_and_optimized(self):
        schema = next(tool.inputSchema for tool in sw_core.TOOLS if tool.name == "sheet_metal_normal_cut")
        self.assertEqual(schema["required"], ["sketch_name"])
        self.assertEqual(schema["properties"]["end_condition"]["default"], "through_all")
        self.assertTrue(schema["properties"]["optimize_geometry"]["default"])

    def test_normal_cut_rejects_invalid_depth_before_com(self):
        with patch.object(sw_sheetmetal, "require_part") as require:
            with self.assertRaises(RuntimeError):
                sw_sheetmetal.sheet_metal_normal_cut({"sketch_name": "Cut", "depth_mm": 0})
            require.assert_not_called()

    def test_saved_sheet_metal_edits_require_a_fresh_token(self):
        doc = SimpleNamespace(GetPathName=lambda: r"C:\vault\production.SLDPRT")
        with patch.object(sw_sheetmetal, "require_part", return_value=(None, doc)), \
                patch("solidworks_mcp.sw_sheetmetal_workflows.require_edit_token", side_effect=RuntimeError("stale")) as guard:
            with self.assertRaisesRegex(RuntimeError, "stale"):
                sw_sheetmetal.set_flat_pattern({"flat": True})
            guard.assert_called_once_with(None)

    def test_every_guarded_sheet_metal_apply_schema_exposes_edit_token(self):
        guarded = {"sheet_metal_base_flange", "edge_flange", "sheet_metal_hem",
                   "sheet_metal_break_corner", "sheet_metal_corner_relief", "sheet_metal_closed_corner",
                   "sheet_metal_jog", "sheet_metal_rip", "sheet_metal_sketched_bend",
                   "sheet_metal_unfold", "sheet_metal_fold", "sheet_metal_normal_cut",
                   "set_sheet_metal_parameters", "set_flat_pattern"}
        schemas = {tool.name: tool.inputSchema for tool in sw_core.TOOLS}
        self.assertEqual(guarded - schemas.keys(), set())
        self.assertTrue(all("edit_token" in schemas[name]["properties"] for name in guarded))

    def test_parameter_edit_uses_native_template_defaults(self):
        template = object()
        ext = SimpleNamespace(GetTemplateSheetMetal=lambda: template)
        with patch.object(sw_sheetmetal, "extension", return_value=ext):
            self.assertIs(sw_sheetmetal._sheet_feature(object(), None), template)

    def test_export_refuses_an_unsaved_part_before_creating_a_file(self):
        doc = SimpleNamespace(GetPathName=lambda: "")
        with patch.object(sw_sheetmetal, "require_part", return_value=(None, doc)), \
                patch.object(sw_sheetmetal, "validated_output_path") as output:
            self.assertFalse(sw_sheetmetal.export_flat_pattern({"path": "part.dxf"})["ok"])
            output.assert_not_called()

    def test_dxf_inspection_counts_geometry_and_bend_layer_entities(self):
        content = "\n".join(("0", "SECTION", "2", "ENTITIES",
                              "0", "LINE", "8", "OUTER", "10", "0", "20", "0",
                              "0", "LINE", "8", "BEND-UP", "10", "1", "20", "1",
                              "0", "ENDSEC", "0", "EOF"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flat.dxf"
            path.write_text(content, encoding="ascii")
            actual = sw_sheetmetal._inspect_dxf(path)
        self.assertEqual(actual["entity_count"], 2)
        self.assertEqual(actual["bend_entity_count"], 1)
        self.assertEqual(actual["layers"], ["BEND-UP", "OUTER"])

    def test_dxf_inspection_accepts_solidworks_up_down_bend_layers(self):
        content = "\n".join(("0", "SECTION", "2", "ENTITIES",
                              "0", "LINE", "8", "0", "10", "0", "20", "0",
                              "0", "LINE", "8", "UP", "10", "1", "20", "1",
                              "0", "LINE", "8", "DOWN", "10", "2", "20", "2",
                              "0", "ENDSEC", "0", "EOF"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "flat.dxf"
            path.write_text(content, encoding="ascii")
            actual = sw_sheetmetal._inspect_dxf(path)
        self.assertEqual(actual["entity_count"], 3)
        self.assertEqual(actual["bend_entity_count"], 2)


class SurfaceBoundaryTests(unittest.TestCase):
    def test_knit_tolerance_is_validated_before_selection(self):
        for tolerance in (0, 1, float("nan")):
            with self.subTest(tolerance=tolerance), patch.object(sw_multibody, "require_part") as require:
                with self.assertRaises(RuntimeError):
                    sw_multibody.knit_surfaces({"selection": {"surface_bodies": [0, 1]}, "tolerance_mm": tolerance})
                require.assert_not_called()

    def test_surface_indices_resolve_from_the_sheet_body_list(self):
        sheet = object()
        doc = object()
        with patch.object(sw_core, "clear_selection"), \
                patch.object(sw_core, "get_bodies", return_value=[sheet]) as bodies, \
                patch.object(sw_core, "select_body", return_value=True) as select:
            self.assertEqual(sw_core.apply_selection(doc, {"surface_bodies": [0]}, mark=1), 1)
            bodies.assert_called_once_with(doc, sw_core.BODY_SHEET)
            select.assert_called_once_with(doc, sheet, 1, True)

    def test_out_of_range_surface_indices_cannot_select_a_solid_body(self):
        with patch.object(sw_core, "clear_selection"), \
                patch.object(sw_core, "get_bodies", return_value=[]) as bodies, \
                patch.object(sw_core, "select_body") as select:
            with self.assertRaises(RuntimeError):
                sw_core.apply_selection(object(), {"surface_bodies": [0]})
            select.assert_not_called()


class WeldmentBoundaryTests(unittest.TestCase):
    def test_only_existing_native_profile_files_are_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            invalid = Path(folder) / "profile.step"
            invalid.write_text("fixture", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                sw_weldment._profile_path(invalid)
            with self.assertRaises(RuntimeError):
                sw_weldment._profile_path(Path(folder) / "missing.sldlfp")

    def test_invalid_group_index_is_rejected_before_feature_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.sldlfp"
            profile.write_bytes(b"fixture")
            with patch.object(sw_weldment, "require_part", return_value=(None, object())), \
                    patch.object(sw_weldment, "exit_active_sketch"), \
                    patch.object(sw_weldment, "sketch_segment_objects", return_value=[object()]), \
                    patch.object(sw_weldment, "feature_manager") as manager:
                with self.assertRaises(RuntimeError):
                    sw_weldment.insert_structural_member({"profile_path": str(profile), "groups": [{"sketch_name": "Path", "segments": [1]}]})
                manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
