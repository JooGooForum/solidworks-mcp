# Copyright 2026 JIALE LIU
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Material readback and package import regressions, without a CAD session."""

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp import sw_drawing, sw_file


def document(kind: int, title: str = "Part1"):
    return SimpleNamespace(
        GetType=lambda: kind,
        GetTitle=lambda: title,
        GetPathName=lambda: "",
        GetSaveFlag=lambda: True,
    )


class DocumentTemplateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def template(self, name: str) -> Path:
        path = self.root / name
        path.write_bytes(b"template")
        return path

    def test_explicit_template_is_passed_exactly_to_new_document(self):
        template = self.template("Custom.PRTDOT")
        app = Mock()
        app.NewDocument.return_value = document(1)
        with patch.object(sw_file, "running_app", return_value=app):
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(template)})
        self.assertTrue(payload["ok"])
        app.NewDocument.assert_called_once_with(str(template.resolve()), 0, 0.0, 0.0)
        app.GetUserPreferenceStringValue.assert_not_called()
        self.assertEqual(payload["data"]["template"]["source"], "explicit")
        self.assertEqual(payload["data"]["template"]["resolved_path"], str(template.resolve()))
        self.assertEqual(payload["data"]["verification"]["actual_document_type"], "part")
        self.assertFalse(payload["data"]["verification"]["source_template_readback_available"])

    def test_missing_explicit_template_never_falls_back(self):
        missing = self.root / "missing.prtdot"
        with patch.object(sw_file, "running_app") as running, \
                patch.object(sw_file, "discover_template") as discover:
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(missing)})
        self.assertFalse(payload["ok"])
        running.assert_not_called()
        discover.assert_not_called()

    def test_wrong_explicit_extension_is_rejected_case_insensitively(self):
        app = Mock()
        wrong = self.template("Drawing.DRWDOT")
        with patch.object(sw_file, "running_app", return_value=app):
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(wrong)})
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["data"]["template"]["extension_valid"])
        app.NewDocument.assert_not_called()

    def test_uppercase_matching_extension_is_accepted(self):
        template = self.template("Plate.PRTDOT")
        app = Mock()
        app.NewDocument.return_value = document(1)
        with patch.object(sw_file, "running_app", return_value=app):
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(template)})
        self.assertTrue(payload["ok"])

    def test_unreadable_explicit_template_is_rejected_before_com(self):
        template = self.template("Locked.prtdot")
        with patch.object(Path, "open", side_effect=PermissionError("denied")), \
                patch.object(sw_file, "running_app") as running:
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(template)})
        self.assertFalse(payload["ok"])
        self.assertIn("not readable", payload["message"])
        running.assert_not_called()

    def test_wrong_result_type_fails_and_leaves_document_available(self):
        template = self.template("Part.prtdot")
        wrong = document(2, "Assembly1")
        app = Mock()
        app.NewDocument.return_value = wrong
        with patch.object(sw_file, "running_app", return_value=app):
            payload = sw_file.create_new_document({"kind": "part", "template_path": str(template)})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["document"]["title"], "Assembly1")
        self.assertEqual(payload["data"]["verification"]["actual_document_type"], "assembly")
        app.CloseDoc.assert_not_called()

    def test_legacy_configured_default_is_preserved(self):
        template = self.template("Default.prtdot")
        app = Mock()
        app.GetUserPreferenceStringValue.return_value = str(template)
        app.NewDocument.return_value = document(1)
        with patch.object(sw_file, "running_app", return_value=app):
            payload = sw_file.create_new_document({"kind": "part"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["template"]["source"], "solidworks_default")

    def test_legacy_discovery_is_preserved(self):
        template = self.template("Found.prtdot")
        app = Mock()
        app.GetUserPreferenceStringValue.return_value = ""
        app.NewDocument.return_value = document(1)
        with patch.object(sw_file, "running_app", return_value=app), \
                patch.object(sw_file, "discover_template", return_value=template):
            payload = sw_file.create_new_document({"kind": "part"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["template"]["source"], "discovered")

    def test_create_drawing_forwards_template_and_reports_sheet_readback(self):
        template = self.template("A4.drwdot")
        sheet = SimpleNamespace(
            GetName=lambda: "Sheet1",
            GetProperties2=lambda: [6, 6, 1.0, 2.0, True, 0.297, 0.21],
            GetTemplateName=lambda: r"C:\formats\A4.slddrt",
        )
        drawing = document(3, "Drawing1")
        drawing.GetCurrentSheet = lambda: sheet
        drawing.GetSheetNames = lambda: ["Sheet1"]
        created = {
            "ok": True,
            "data": {
                "template": {"resolved_path": str(template), "source": "explicit"},
                "verification": {"actual_document_type": "drawing"},
            },
        }
        with patch.object(sw_drawing, "new_document", return_value=created) as new_doc, \
                patch.object(sw_drawing, "require_drawing", return_value=(Mock(), drawing)):
            payload = sw_drawing.create_drawing({"template_path": str(template)})
        new_doc.assert_called_once_with("drawing", str(template))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["sheet_size_mm"], [297.0, 210.0])
        self.assertEqual(payload["data"]["scale"], [1.0, 2.0])
        self.assertTrue(payload["data"]["first_angle"])
        self.assertEqual(payload["data"]["sheet_format_path"], r"C:\formats\A4.slddrt")

    def test_create_drawing_preserves_sheet_format_when_applying_overrides(self):
        template = self.template("A4.drwdot")
        sheet = SimpleNamespace(
            GetName=lambda: "Sheet1",
            GetProperties2=lambda: [8, 8, 1.0, 2.0, False, 0.42, 0.297],
            GetTemplateName=lambda: r"C:\formats\A4.slddrt",
        )
        drawing = document(3, "Drawing1")
        drawing.GetCurrentSheet = lambda: sheet
        drawing.GetSheetNames = lambda: ["Sheet1", "DWG"]
        drawing.SetupSheet5 = Mock()
        created = {
            "ok": True,
            "data": {"template": {}, "verification": {}},
        }
        with patch.object(sw_drawing, "new_document", return_value=created), \
                patch.object(sw_drawing, "require_drawing", return_value=(Mock(), drawing)):
            payload = sw_drawing.create_drawing({"template_path": str(template), "first_angle": True})
        self.assertTrue(payload["ok"])
        setup = drawing.SetupSheet5.call_args.args
        self.assertEqual(setup[3:5], (1.0, 2.0))
        self.assertTrue(setup[5])
        self.assertEqual(setup[6], r"C:\formats\A4.slddrt")
        self.assertEqual([item["name"] for item in payload["data"]["sheets"]], ["Sheet1", "DWG"])

    def test_create_drawing_without_overrides_does_not_reset_sheet(self):
        template = self.template("A4.drwdot")
        sheet = SimpleNamespace(
            GetName=lambda: "Sheet1",
            GetProperties2=lambda: [8, 8, 1.0, 1.0, True, 0.42, 0.297],
            GetTemplateName=lambda: r"C:\formats\A4.slddrt",
        )
        drawing = document(3, "Drawing1")
        drawing.GetCurrentSheet = lambda: sheet
        drawing.GetSheetNames = lambda: ["Sheet1"]
        drawing.SetupSheet5 = Mock()
        created = {"ok": True, "data": {"template": {}, "verification": {}}}
        with patch.object(sw_drawing, "new_document", return_value=created), \
                patch.object(sw_drawing, "require_drawing", return_value=(Mock(), drawing)):
            payload = sw_drawing.create_drawing({"template_path": str(template)})
        self.assertTrue(payload["ok"])
        drawing.SetupSheet5.assert_not_called()


class AutoDimensionViewTests(unittest.TestCase):
    def drawing(self, *, activate=True, select=True, active_name="Drawing View2"):
        state = {"dimensions": 0, "annotations": []}
        layer_state = {"current": "Dimensions"}
        layer_manager = SimpleNamespace(
            GetCurrentLayer=lambda: layer_state["current"],
            SetCurrentLayer=lambda name: layer_state.update(current=name) or True,
            GetLayerList=lambda: ["Dimensions"],
        )
        view = SimpleNamespace(
            GetName2=lambda: "Drawing View2",
            Type=4,
            GetDimensionCount4=lambda: state["dimensions"],
            GetNextView=lambda: None,
        )
        sheet = SimpleNamespace(
            GetName2=lambda: "Sheet1",
            Type=1,
            GetNextView=lambda: view,
        )
        ext = Mock()
        ext.SelectByID2.return_value = select
        ext.GetAnnotations.side_effect = lambda: state["annotations"]
        ext.GetUserPreferenceString.return_value = "Dimensions"
        activate_view = Mock(return_value=activate)
        annotation = SimpleNamespace(
            Layer="",
            LayerOverride=3,
            GetType=lambda: 4,
            GetName=lambda: "D1@Drawing View2",
            GetPosition=lambda: [0.1, 0.2, 0.0],
            GetSpecificAnnotation=lambda: SimpleNamespace(Type2=2),
        )
        def create_dimensions(*_args):
            state.update(dimensions=5)
            state["annotations"] = [annotation]
            return 0
        auto_dimension = Mock(side_effect=create_dimensions)
        doc = SimpleNamespace(
            GetFirstView=lambda: sheet,
            ActivateView=activate_view,
            ActiveDrawingView=view if active_name == "Drawing View2" else SimpleNamespace(GetName2=lambda: active_name),
            Extension=ext,
            GetLayerManager=lambda: layer_manager,
            AutoDimension=auto_dimension,
            ClearSelection2=lambda _all: None,
            EditRebuild3=lambda: True,
        )
        return doc, ext

    def test_selects_requested_view_before_auto_dimensioning(self):
        doc, ext = self.drawing()
        with patch.object(sw_drawing, "require_drawing", return_value=(Mock(), doc)), \
                patch.object(sw_drawing, "rebuild", return_value=[]):
            payload = sw_drawing.auto_dimension_view({"view_name": "Drawing View2"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["dimensions_added"], 5)
        self.assertEqual(payload["data"]["view_name"], "Drawing View2")
        ext.SelectByID2.assert_called_once()
        self.assertEqual(ext.SelectByID2.call_args.args[:2], ("Drawing View2", "DRAWINGVIEW"))

    def test_refuses_when_requested_view_did_not_become_active(self):
        doc, _ = self.drawing(active_name="Drawing View4")
        with patch.object(sw_drawing, "require_drawing", return_value=(Mock(), doc)):
            payload = sw_drawing.auto_dimension_view({"view_name": "Drawing View2"})
        self.assertFalse(payload["ok"])
        doc.AutoDimension.assert_not_called()

    def test_refuses_when_requested_view_cannot_be_activated(self):
        doc, _ = self.drawing(activate=False)
        with patch.object(sw_drawing, "require_drawing", return_value=(Mock(), doc)):
            payload = sw_drawing.auto_dimension_view({"view_name": "Missing View"})
        self.assertFalse(payload["ok"])
        doc.AutoDimension.assert_not_called()

    def test_refuses_when_requested_view_cannot_be_selected(self):
        doc, _ = self.drawing(select=False)
        with patch.object(sw_drawing, "require_drawing", return_value=(Mock(), doc)):
            payload = sw_drawing.auto_dimension_view({"view_name": "Drawing View2"})
        self.assertFalse(payload["ok"])
        doc.AutoDimension.assert_not_called()


class MaterialReadbackTests(unittest.TestCase):
    def test_byref_name(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.return_value = "AISI 1020"
        self.assertEqual(sw_file._material_readback(doc, "Materials"), "AISI 1020")
        doc.GetMaterialPropertyName2.assert_called_once()

    def test_tuple_return(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.return_value = ("AISI 1020", "Materials")
        self.assertEqual(sw_file._material_readback(doc, "Materials"), "AISI 1020")

    def test_plain_string_fallback(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.side_effect = [TypeError("byref unsupported"), "Steel"]
        self.assertEqual(sw_file._material_readback(doc, "Materials"), "Steel")

    def test_material_id_fallback(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.return_value = ""
        doc.MaterialIdName = "Materials|Steel"
        self.assertEqual(sw_file._material_readback(doc, "Materials"), "Steel")

    def test_missing_material(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.return_value = ""
        doc.MaterialIdName = ""
        self.assertEqual(sw_file._material_readback(doc, "Materials"), "")

    def test_unknown_material_is_not_reported_as_applied(self):
        doc = Mock()
        doc.GetMaterialPropertyName2.return_value = "Previous material"
        with patch.object(sw_file, "require_part", return_value=(None, doc)), \
                patch.object(sw_file, "rebuild"):
            payload = sw_file.set_material({"name": "Missing material"})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["material"], "Previous material")


class PackageImportTests(unittest.TestCase):
    def test_deferred_helper_imports_resolve_in_package_context(self):
        # Server import alone never executes imports hidden inside handlers.
        # Resolve those imports too, without invoking geometry-changing tools.
        root = Path(sw_file.__file__).parent
        for source in root.glob("sw_*.py"):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if not (node.module or "").startswith("sw_"):
                    continue
                with self.subTest(source=source.name, line=node.lineno):
                    module = importlib.import_module(
                        "." * node.level + node.module, "solidworks_mcp"
                    )
                    for alias in node.names:
                        self.assertTrue(hasattr(module, alias.name), alias.name)

