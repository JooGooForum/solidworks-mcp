from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp import sw_feature


def feature(name: str, rolled_back: bool):
    return SimpleNamespace(Name=name, IsRolledBack=lambda: rolled_back)


class RollbackToolTests(unittest.TestCase):
    def _patches(self, features, manager=None):
        doc = Mock()
        manager = manager or Mock()
        return doc, manager, (
            patch.object(sw_feature, "require_part", return_value=(None, doc)),
            patch.object(sw_feature, "exit_active_sketch"),
            patch.object(sw_feature, "feature_manager", return_value=manager),
            patch.object(sw_feature, "iter_feature_objects", return_value=features),
        )

    def test_end_rolls_forward_rebuilds_and_verifies(self):
        doc, manager, patches = self._patches([feature("Base", False), feature("Cut", False)])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(sw_feature, "rebuild", return_value=True) as rebuild, \
                patch.object(sw_feature, "whats_wrong", return_value=[]):
            payload = sw_feature.set_rollback_bar({"position": "end"})
        self.assertTrue(payload["ok"])
        manager.EditRollback.assert_called_once_with(1, "")
        rebuild.assert_called_once_with(doc)
        self.assertEqual(payload["data"]["rolled_back_features"], [])
        self.assertFalse(payload["data"]["saved"])

    def test_before_feature_requires_exact_existing_name(self):
        doc, manager, patches = self._patches([])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(sw_feature, "find_feature", return_value=None):
            payload = sw_feature.set_rollback_bar({"position": "before_feature", "feature_name": "Missing"})
        self.assertFalse(payload["ok"])
        manager.EditRollback.assert_not_called()

    def test_before_feature_verifies_target_is_rolled_back(self):
        target = feature("Sketch9", True)
        doc, manager, patches = self._patches([feature("Base", False), target])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(sw_feature, "find_feature", return_value=target):
            payload = sw_feature.set_rollback_bar({"position": "before_feature", "feature_name": "Sketch9"})
        self.assertTrue(payload["ok"])
        manager.EditRollback.assert_called_once_with(3, "Sketch9")

    def test_after_feature_verifies_target_is_not_rolled_back(self):
        target = feature("Sketch9", False)
        doc, manager, patches = self._patches([feature("Base", False), target, feature("Fold1", True)])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(sw_feature, "find_feature", return_value=target):
            payload = sw_feature.set_rollback_bar({"position": "after_feature", "feature_name": "Sketch9"})
        self.assertTrue(payload["ok"])
        manager.EditRollback.assert_called_once_with(4, "Sketch9")

    def test_end_fails_when_any_feature_remains_rolled_back(self):
        doc, manager, patches = self._patches([feature("Fold1", True)])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(sw_feature, "rebuild", return_value=True), \
                patch.object(sw_feature, "whats_wrong", return_value=[]):
            payload = sw_feature.set_rollback_bar({"position": "end"})
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
