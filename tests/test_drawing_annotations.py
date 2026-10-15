from __future__ import annotations

import unittest
from unittest.mock import patch

from solidworks_mcp import sw_drawing


class FakeLayerManager:
    def __init__(self, layers=None) -> None:
        self.layers = layers or ["Dimensions", "Notes", "Symbols"]

    def GetLayerList(self):
        return self.layers


class FakeDisplayDimension:
    def __init__(self, dimension_type: int, hole_callout: bool = False) -> None:
        self.Type2 = dimension_type
        self.IsHoleCallout = hole_callout


class FakeAnnotation:
    def __init__(self, annotation_type: int, *, dimension_type: int = 0,
                 name: str = "Annotation1", layer: str = "", override: int = 3,
                 accept_layer: bool = True, hole_callout: bool = False) -> None:
        self.annotation_type = annotation_type
        self.dimension_type = dimension_type
        self.name = name
        self._layer = layer
        self.LayerOverride = override
        self.accept_layer = accept_layer
        self.hole_callout = hole_callout

    def GetType(self):
        return self.annotation_type

    def GetName(self):
        return self.name

    def GetPosition(self):
        return [0.1, 0.2, 0.0]

    def GetSpecificAnnotation(self):
        return FakeDisplayDimension(self.dimension_type, self.hole_callout)

    @property
    def Layer(self):
        return self._layer

    @Layer.setter
    def Layer(self, value):
        if self.accept_layer:
            self._layer = value


class FakeExtension:
    def __init__(self, annotations=None, mappings=None, problems=None) -> None:
        self.annotations = annotations or []
        self.mappings = mappings or {}
        self.problems = problems or []

    def GetAnnotations(self):
        return self.annotations

    def GetUserPreferenceString(self, preference, option):
        self.last_preference = preference
        return self.mappings.get(option, "")

    def GetWhatsWrong(self, *_args):
        if not self.problems:
            return None
        return [None, self.problems, [1] * len(self.problems), [False] * len(self.problems)]


class FakeDocument:
    def __init__(self, annotations=None, mappings=None, layers=None, problems=None) -> None:
        self.Extension = FakeExtension(annotations, mappings, problems)
        self.manager = FakeLayerManager(layers)
        self.rebuilds = 0
        self.center_layers = {
            sw_drawing.CENTERMARK_LAYER_PREFERENCE: "Symbols",
            sw_drawing.CENTERLINE_LAYER_PREFERENCE: "Symbols",
        }

    def GetLayerManager(self):
        return self.manager

    def GetUserPreferenceStringValue(self, preference):
        return self.center_layers.get(preference, "")

    def EditRebuild3(self):
        self.rebuilds += 1
        return True


class DrawingAnnotationLayerTests(unittest.TestCase):
    def test_every_dimension_subtype_maps_to_document_preference(self):
        expected = {
            0: 200, 1: 207, 2: 206, 3: 201, 4: 202, 5: 208, 6: 204,
            7: 207, 8: 207, 9: 200, 10: 203, 11: 206, 12: 206,
            13: 206, 14: 206, 15: 206, 16: 207,
        }
        for dimension_type, option in expected.items():
            with self.subTest(dimension_type=dimension_type):
                kind = sw_drawing._annotation_kind(FakeAnnotation(4, dimension_type=dimension_type))
                self.assertEqual(kind["preference_option"], option)

    def test_annotation_categories_map_to_document_preferences(self):
        expected = {2: 102, 5: 103, 6: 104, 7: 105, 8: 106, 14: 150, 18: 107}
        for annotation_type, option in expected.items():
            with self.subTest(annotation_type=annotation_type):
                kind = sw_drawing._annotation_kind(FakeAnnotation(annotation_type))
                self.assertEqual(kind["preference_option"], option)

    def test_specific_dimension_mapping_is_assigned_and_verified(self):
        annotation = FakeAnnotation(4, dimension_type=6)
        doc = FakeDocument(mappings={204: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
        self.assertTrue(outcome["ok"])
        self.assertEqual(annotation.Layer, "Dimensions")
        self.assertEqual(annotation.LayerOverride, 0)
        self.assertEqual(outcome["annotations"][0]["subtype"], "diameter")
        self.assertTrue(outcome["annotations"][0]["verified"])

    def test_general_mapping_is_used_for_unknown_dimension(self):
        annotation = FakeAnnotation(4, dimension_type=99)
        doc = FakeDocument(mappings={200: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["annotations"][0]["preference_option"], 200)

    def test_hole_callout_takes_precedence_over_dimension_type(self):
        annotation = FakeAnnotation(4, dimension_type=6, hole_callout=True)
        doc = FakeDocument(mappings={205: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["annotations"][0]["subtype"], "hole")
        self.assertEqual(outcome["annotations"][0]["preference_option"], 205)

    def test_center_mark_uses_its_dedicated_document_preference(self):
        annotation = FakeAnnotation(13)
        doc = FakeDocument()
        self.assertEqual(sw_drawing._standard_layer(doc, annotation)["expected_layer"], "Symbols")

    def test_empty_none_format_and_missing_layers_fail_without_mutation(self):
        for mapping in ["", "None", "FORMAT", "Missing"]:
            with self.subTest(mapping=mapping):
                annotation = FakeAnnotation(6, layer="Notes", override=5)
                doc = FakeDocument(mappings={104: mapping})
                outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
                self.assertFalse(outcome["ok"])
                self.assertEqual((annotation.Layer, annotation.LayerOverride), ("Notes", 5))

    def test_mismatched_readback_restores_original_values(self):
        annotation = FakeAnnotation(6, layer="Notes", override=5, accept_layer=False)
        doc = FakeDocument(mappings={104: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
        self.assertFalse(outcome["ok"])
        self.assertEqual((annotation.Layer, annotation.LayerOverride), ("Notes", 5))
        self.assertEqual(outcome["restored"], 1)
        self.assertFalse(outcome["annotations"][0]["verified"])
        self.assertEqual(outcome["annotations"][0]["actual_layer"], "Notes")

    def test_partial_assignment_failure_restores_every_new_annotation(self):
        first = FakeAnnotation(6, name="First", layer="Notes", override=5)
        second = FakeAnnotation(6, name="Second", layer="Notes", override=6, accept_layer=False)
        doc = FakeDocument(mappings={104: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [], [first, second])
        self.assertFalse(outcome["ok"])
        self.assertEqual((first.Layer, first.LayerOverride), ("Notes", 5))
        self.assertEqual((second.Layer, second.LayerOverride), ("Notes", 6))

    def test_rebuild_problem_restores_assignment(self):
        annotation = FakeAnnotation(6, layer="Notes", override=5)
        doc = FakeDocument(mappings={104: "Dimensions"}, problems=["BrokenFeature"])
        outcome = sw_drawing._apply_standard_layers(doc, [], [annotation])
        self.assertFalse(outcome["ok"])
        self.assertEqual((annotation.Layer, annotation.LayerOverride), ("Notes", 5))

    def test_fallback_rejects_ambiguous_existing_fingerprint(self):
        existing = FakeAnnotation(6, name="Same")
        created = FakeAnnotation(6, name="Same")
        doc = FakeDocument([existing, created], mappings={104: "Notes"})
        outcome = sw_drawing._apply_standard_layers(doc, [existing])
        self.assertFalse(outcome["ok"])
        self.assertIn("could not be distinguished", outcome["error"])

    def test_preexisting_template_annotation_is_not_touched(self):
        template = FakeAnnotation(6, name="Title", layer="Notes", override=4)
        created = FakeAnnotation(4, dimension_type=2)
        doc = FakeDocument([template, created], mappings={206: "Dimensions"})
        outcome = sw_drawing._apply_standard_layers(doc, [template], [created])
        self.assertTrue(outcome["ok"])
        self.assertEqual((template.Layer, template.LayerOverride), ("Notes", 4))

    def test_inspector_reports_layers_mappings_annotations_and_invalid_entries(self):
        annotation = FakeAnnotation(6, layer="Notes", override=0)
        mappings = {option: "Dimensions" for option in sw_drawing.STANDARD_LAYER_OPTIONS.values()}
        mappings[104] = "Notes"
        mappings[105] = "Missing"
        doc = FakeDocument([annotation], mappings=mappings)
        with patch.object(sw_drawing, "require_drawing", return_value=(object(), doc)):
            outcome = sw_drawing.inspect_drawing_layer_standard({})
        self.assertTrue(outcome["ok"])
        data = outcome["data"]
        self.assertIn("Dimensions", data["layers"])
        self.assertEqual(data["standard_mappings"]["note"], "Notes")
        self.assertEqual(data["annotations"][0]["actual_layer"], "Notes")
        self.assertIn(
            {"category": "surface_finish", "configured_layer": "Missing"},
            data["invalid_mappings"],
        )


if __name__ == "__main__":
    unittest.main()
