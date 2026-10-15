from __future__ import annotations

import unittest

from solidworks_mcp import sw_drawing


class FakeLayerManager:
    def __init__(self, current: str = "Dimensions") -> None:
        self.current = current
        self.selections: list[str] = []

    def GetCurrentLayer(self) -> str:
        return self.current

    def SetCurrentLayer(self, name: str) -> bool:
        self.selections.append(name)
        self.current = name
        return True


class FakeDocument:
    def __init__(self, manager: FakeLayerManager | None) -> None:
        self.manager = manager

    def GetLayerManager(self):
        return self.manager


class FakeAnnotation:
    def __init__(self, layer: str = "Dimensions", override: int = 7) -> None:
        self.Layer = layer
        self.LayerOverride = override


class FakeAnnotationOwner:
    def __init__(self, annotation: FakeAnnotation) -> None:
        self.annotation = annotation

    def GetAnnotation(self) -> FakeAnnotation:
        return self.annotation


class DrawingAnnotationLayerTests(unittest.TestCase):
    def test_creation_uses_per_standard_and_restores_previous_layer(self):
        manager = FakeLayerManager()
        with sw_drawing._create_annotations_per_standard(FakeDocument(manager)) as state:
            self.assertEqual(manager.current, sw_drawing.PER_STANDARD_LAYER)
            self.assertEqual(state["creation_layer"], sw_drawing.PER_STANDARD_LAYER)

        self.assertEqual(manager.current, "Dimensions")
        self.assertEqual(manager.selections, [sw_drawing.PER_STANDARD_LAYER, "Dimensions"])

    def test_creation_restores_layer_after_native_failure(self):
        manager = FakeLayerManager("Notes")
        with self.assertRaisesRegex(RuntimeError, "native failure"):
            with sw_drawing._create_annotations_per_standard(FakeDocument(manager)):
                raise RuntimeError("native failure")

        self.assertEqual(manager.current, "Notes")

    def test_missing_layer_manager_fails_instead_of_silently_using_current_layer(self):
        with self.assertRaisesRegex(RuntimeError, "layer manager"):
            with sw_drawing._create_annotations_per_standard(FakeDocument(None)):
                pass

    def test_returned_annotation_layers_are_read_without_reassignment(self):
        direct = FakeAnnotation()
        owned = FakeAnnotation("Notes", 2)
        report = sw_drawing._read_annotation_layers([direct, FakeAnnotationOwner(owned)])

        self.assertEqual(report["annotations_created_with_per_standard"], 2)
        self.assertEqual(
            report["annotation_layer_readback"],
            [
                {"layer": "Dimensions", "layer_override": 7},
                {"layer": "Notes", "layer_override": 2},
            ],
        )
        self.assertEqual((direct.Layer, direct.LayerOverride), ("Dimensions", 7))
        self.assertEqual((owned.Layer, owned.LayerOverride), ("Notes", 2))

    def test_unrelated_template_annotations_are_not_touched(self):
        template_annotation = FakeAnnotation("Title Block", 3)
        created_annotation = FakeAnnotation("Dimensions", 7)

        sw_drawing._read_annotation_layers([created_annotation])

        self.assertEqual(template_annotation.Layer, "Title Block")
        self.assertEqual(template_annotation.LayerOverride, 3)


if __name__ == "__main__":
    unittest.main()
