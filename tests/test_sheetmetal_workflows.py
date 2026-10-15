import math
import unittest
from unittest.mock import patch

from solidworks_mcp import sw_core, sw_sheetmetal_workflows as workflows


class SheetMetalWorkflowTests(unittest.TestCase):
    def test_public_tool_schemas_require_job_parameters_and_dimension_mode(self):
        tool = next(item for item in sw_core.TOOLS if item.name == "create_sheet_metal_plate")
        self.assertEqual(tool.inputSchema["required"],
                         ["width_mm", "height_mm", "thickness_mm", "inside_radius_mm", "dimension_mode"])
        self.assertEqual(tool.inputSchema["properties"]["dimension_mode"]["enum"],
                         ["finished_outer", "flat_blank"])
        panel = next(item for item in sw_core.TOOLS if item.name == "create_sheet_metal_panel")
        self.assertEqual(panel.inputSchema["required"],
                         ["width_mm", "height_mm", "thickness_mm", "inside_radius_mm", "dimension_mode"])
        for name in ("edge_flanges", "hems", "break_corners", "closed_corners", "corner_reliefs"):
            self.assertIn(name, panel.inputSchema["properties"])

    def test_missing_template_never_creates_a_document(self):
        with patch.object(workflows, "_resolve_template", return_value=None), patch.object(workflows, "running_app") as app:
            payload = workflows.create_sheet_metal_plate({"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5,
                "inside_radius_mm": 1.8, "dimension_mode": "flat_blank"})
        self.assertFalse(payload["ok"])
        app.assert_not_called()

    def test_stale_token_is_rejected(self):
        with patch.object(workflows, "_snapshot", return_value={"document": {"title": "A"}}):
            with self.assertRaisesRegex(RuntimeError, "stale"):
                workflows.require_edit_token("wrong")

    def test_token_is_stable_for_equal_snapshots(self):
        left = {"document": {"title": "A"}, "features": [{"name": "Sheet-Metal1"}]}
        right = {"features": [{"name": "Sheet-Metal1"}], "document": {"title": "A"}}
        self.assertEqual(workflows._token(left), workflows._token(right))

    def test_token_changes_when_persistent_topology_changes(self):
        left = {"document": {"title": "A"}, "topology": {"edge_references": ["edge-a"]}}
        right = {"document": {"title": "A"}, "topology": {"edge_references": ["edge-b"]}}
        self.assertNotEqual(workflows._token(left), workflows._token(right))

    def test_invalid_numeric_inputs_are_rejected_before_template_lookup(self):
        for key, value in (("width_mm", 0), ("height_mm", math.nan), ("thickness_mm", -1)):
            args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5,
                    "inside_radius_mm": 1.8, "dimension_mode": "flat_blank"}
            args[key] = value
            with self.subTest(key=key), patch.object(workflows, "_resolve_template") as resolve:
                with self.assertRaises(RuntimeError):
                    workflows.create_sheet_metal_plate(args)
                resolve.assert_not_called()

    def test_alignment_apply_rejects_stale_token_before_com(self):
        with patch.object(workflows, "active_document") as active, \
                patch.object(workflows, "_snapshot", return_value={"document": {"title": "A"}}):
            with self.assertRaisesRegex(RuntimeError, "stale"):
                workflows.set_sketch_line_collinear_to_edge({"sketch_name": "S", "sketch_segment_index": 0,
                    "edge_index": 0, "edit_token": "wrong"})
            active.assert_not_called()

    def test_alignment_schema_binds_exact_inspected_references(self):
        tool = next(item for item in sw_core.TOOLS if item.name == "set_sketch_line_collinear_to_edge")
        self.assertIn("sketch_segment_reference", tool.inputSchema["required"])
        self.assertIn("model_edge_reference", tool.inputSchema["required"])

    def test_alignment_direction_and_gap_helpers(self):
        self.assertEqual(workflows._unit_direction([0, 0, 0], [2, 0, 0]), [1.0, 0.0, 0.0])
        self.assertIsNone(workflows._unit_direction([1, 1, 1], [1, 1, 1]))
        self.assertAlmostEqual(workflows._point_line_gap([0, 3, 0], [0, 0, 0], [1, 0, 0]), 3)

    def test_panel_validates_flange_before_creating_plate(self):
        args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5, "inside_radius_mm": 1.8,
                "dimension_mode": "flat_blank", "flange_sides": ["left"], "flange_height_mm": 0}
        with patch.object(workflows, "create_sheet_metal_plate") as create:
            with self.assertRaises(RuntimeError):
                workflows.create_sheet_metal_panel(args)
            create.assert_not_called()

    def test_explicit_panel_flange_declarations_are_validated_before_creation(self):
        args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5, "inside_radius_mm": 1.8,
                "dimension_mode": "flat_blank", "edge_flanges": [
                    {"side": "left", "height_mm": 20}, {"side": "left", "height_mm": 30}]}
        with patch.object(workflows, "create_sheet_metal_plate") as create:
            with self.assertRaisesRegex(RuntimeError, "only one"):
                workflows.create_sheet_metal_panel(args)
            create.assert_not_called()

    def test_panel_post_features_are_validated_before_creation(self):
        args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5, "inside_radius_mm": 1.8,
                "dimension_mode": "flat_blank", "edge_flanges": [{"side": "left", "height_mm": 20}],
                "hems": [{"side": "top", "hem_type": "open", "length_mm": 8}]}
        with patch.object(workflows, "create_sheet_metal_plate") as create:
            with self.assertRaisesRegex(RuntimeError, "no declared edge flange"):
                workflows.create_sheet_metal_panel(args)
            create.assert_not_called()

    def test_panel_requires_legacy_or_explicit_flange_declarations(self):
        args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5, "inside_radius_mm": 1.8,
                "dimension_mode": "flat_blank"}
        with patch.object(workflows, "create_sheet_metal_plate") as create:
            with self.assertRaisesRegex(RuntimeError, "Provide edge_flanges"):
                workflows.create_sheet_metal_panel(args)
            create.assert_not_called()

    def test_panel_orchestrates_declarative_post_features_by_semantic_side(self):
        args = {"width_mm": 100, "height_mm": 50, "thickness_mm": 1.5, "inside_radius_mm": 1.8,
                "dimension_mode": "flat_blank",
                "edge_flanges": [{"side": "left", "height_mm": 20},
                                  {"side": "top", "height_mm": 25}],
                "hems": [{"side": "left", "hem_type": "open", "length_mm": 8}],
                "break_corners": [{"side": "top", "corner_type": "fillet", "size_mm": 2}],
                "closed_corners": [{"extend_side": "left", "match_side": "top", "gap_mm": 1}],
                "corner_reliefs": [{"side_a": "left", "side_b": "top",
                                    "relief_type": "square", "relief_size_mm": 3}]}
        ok = {"ok": True, "data": {}}
        with patch.object(workflows, "create_sheet_metal_plate", return_value=ok), \
                patch.object(workflows, "_rectangle_side_edges", side_effect=[[4], [7]]), \
                patch.object(workflows.sw_sheetmetal, "edge_flange", return_value=ok) as flange, \
                patch.object(workflows, "active_document", return_value=(None, object())), \
                patch.object(workflows, "_outer_edge_for_flange", side_effect=[14, 17]), \
                patch.object(workflows, "_wall_face_for_flange", side_effect=[21, 22, 23, 24]), \
                patch.object(workflows.sw_sheetmetal, "sheet_metal_hem", return_value=ok) as hem, \
                patch.object(workflows.sw_sheetmetal, "sheet_metal_break_corner", return_value=ok) as broken, \
                patch.object(workflows.sw_sheetmetal, "sheet_metal_closed_corner", return_value=ok) as closed, \
                patch.object(workflows.sw_sheetmetal, "sheet_metal_corner_relief", return_value=ok) as relief, \
                patch.object(workflows, "_snapshot", return_value={"problems": []}):
            payload = workflows.create_sheet_metal_panel(args)
        self.assertTrue(payload["ok"])
        self.assertEqual(flange.call_count, 2)
        self.assertEqual(hem.call_args.args[0]["selection"], {"edges": [14]})
        self.assertEqual(broken.call_args.args[0]["selection"], {"edges": [17]})
        self.assertEqual(closed.call_args.args[0]["faces_to_extend"], [21])
        self.assertEqual(closed.call_args.args[0]["faces_to_match"], [22])
        self.assertEqual(relief.call_args.args[0]["selection"], {"faces": [23, 24]})
        self.assertEqual([item["kind"] for item in payload["data"]["operations"]],
                         ["edge_flange", "edge_flange", "hem", "break_corner", "closed_corner", "corner_relief"])


if __name__ == "__main__":
    unittest.main()
