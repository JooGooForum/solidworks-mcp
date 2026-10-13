# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from solidworks_mcp import sw_motion


class FakeDefinition:
    """Stands in for ISimulation*FeatureData, including its property readback."""

    def __init__(self, apply_settings=True):
        self.Strength = 0.0
        self.ReverseDirection = False
        self.Axis = 0
        self.DirectionReference = None
        self.Velocity = 0.0
        self.MotorType = 0
        self.speed = None
        self.apply_settings = apply_settings

    def _FlagAsMethod(self, name):
        return None

    def ConstantSpeedMotor(self, speed):
        self.speed = speed
        if self.apply_settings:
            self.Velocity = speed


def fake_feature(name="Gravity1", kind="AEMGravity"):
    return SimpleNamespace(Name=name, GetTypeName2=lambda: kind)


class MotionBoundaryTests(unittest.TestCase):
    def test_invalid_timeline_is_rejected_before_com(self):
        for args in ({"duration_sec": 0}, {"time_sec": -1}, {"time_sec": float("nan")}, {}):
            with self.subTest(args=args), patch.object(sw_motion, "_manager") as manager:
                with self.assertRaises(RuntimeError):
                    sw_motion.set_motion_study_timing({"name": "study", **args})
                manager.assert_not_called()

    def test_out_of_bounds_cursor_cannot_change_duration(self):
        with patch.object(sw_motion, "_manager") as manager, patch.object(sw_motion, "_study") as study, \
                patch.object(sw_motion, "_info", return_value={"duration_sec": 5}):
            with self.assertRaises(RuntimeError):
                sw_motion.set_motion_study_timing({"name": "study", "duration_sec": 6, "time_sec": 7})
            manager.return_value.ActivateMotionStudy.assert_not_called()
            study.return_value.SetDuration.assert_not_called()

    def test_unavailable_solver_is_not_assigned(self):
        study = SimpleNamespace(StudyType=1)
        with patch.object(sw_motion, "_supported", return_value=1), patch.object(sw_motion, "_info", return_value={}):
            self.assertFalse(sw_motion._set_type(study, 4)["ok"])
        self.assertEqual(study.StudyType, 1)

    def test_supported_type_mask_reads_byref_output(self):
        def supported(mask):
            mask.value = 3
            return True
        self.assertEqual(sw_motion._supported(SimpleNamespace(GetSupportedStudyTypes=supported)), 3)


class MotionFeatureDataTests(unittest.TestCase):
    def test_gravity_strength_and_axis_come_from_the_definition(self):
        definition = FakeDefinition()
        study = SimpleNamespace(
            CreateDefinition=lambda kind: definition,
            CreateFeature=lambda data: fake_feature(),
            GetMotionFeatures=lambda: [fake_feature()],
            GetMotionFeaturesCount=lambda: 1,
        )
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True):
            payload = sw_motion.add_motion_gravity(
                {"name": "Solve", "strength": 12.0, "axis": "z", "reverse_direction": True})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["definition"], {"strength": 12.0, "reverse_direction": True, "axis": 2})

    def test_gravity_rejects_invalid_strength_before_com(self):
        for strength in (0, -1, float("inf"), float("nan")):
            with self.subTest(strength=strength), patch.object(sw_motion, "_manager") as manager:
                with self.assertRaises(RuntimeError):
                    sw_motion.add_motion_gravity({"name": "Solve", "strength": strength})
                manager.assert_not_called()

    def test_gravity_is_refused_on_a_part_before_touching_the_motion_manager(self):
        part = SimpleNamespace(GetType=lambda: 1)
        with patch.object(sw_motion, "active_document", return_value=(None, part)), \
                patch.object(sw_motion, "extension") as extension:
            payload = sw_motion.add_motion_gravity({"name": "Solve", "strength": 9.81})
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["data"]["document_type"], "part")
        self.assertIn("assembly", payload["message"].lower())
        extension.assert_not_called()

    def test_motor_is_refused_on_a_part_before_touching_the_motion_manager(self):
        part = SimpleNamespace(GetType=lambda: 1)
        with patch.object(sw_motion, "active_document", return_value=(None, part)), \
                patch.object(sw_motion, "extension") as extension:
            payload = sw_motion.add_motion_motor({"name": "Solve", "motor_type": "linear",
                                                  "direction": {"edges": [0]}, "speed": 25.0})
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["data"]["document_type"], "part")
        extension.assert_not_called()

    def test_gravity_is_not_confirmed_when_the_definition_ignores_it(self):
        definition = FakeDefinition()
        study = SimpleNamespace(
            CreateDefinition=lambda kind: definition,
            CreateFeature=lambda data: fake_feature(),
            GetMotionFeatures=lambda: [fake_feature()],
            GetMotionFeaturesCount=lambda: 1,
        )

        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(FakeDefinition, "Strength", property(lambda self: 0.0, lambda self, value: None), create=True):
            payload = sw_motion.add_motion_gravity({"name": "Solve", "strength": 12.0})
        self.assertFalse(payload["ok"], payload)

    def test_motor_speed_and_type_are_read_back(self):
        reference = object()
        definition = FakeDefinition()
        definition.MotorType = 1
        study = SimpleNamespace(
            CreateDefinition=lambda kind: definition,
            CreateFeature=lambda data: fake_feature("RotaryMotor1", "AEMRotationalMotor"),
            GetMotionFeatures=lambda: [fake_feature("RotaryMotor1", "AEMRotationalMotor")],
            GetMotionFeaturesCount=lambda: 1,
        )
        selection_manager = SimpleNamespace(GetSelectedObject6=lambda mark, index: reference,
                                            _FlagAsMethod=lambda name: None)
        doc = SimpleNamespace(SelectionManager=selection_manager)
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "require_selection", return_value=1), \
                patch.object(sw_motion, "active_document", return_value=(None, doc)):
            payload = sw_motion.add_motion_motor(
                {"name": "Solve", "motor_type": "rotational", "direction": {"edges": [0]}, "speed": 30.0})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["definition"]["speed"], 30.0)
        self.assertEqual(payload["data"]["definition"]["motor_type"], 1)
        self.assertIs(definition.DirectionReference, reference)

    def test_motor_is_not_confirmed_when_the_speed_is_dropped(self):
        definition = FakeDefinition(apply_settings=False)
        definition.MotorType = 1
        study = SimpleNamespace(
            CreateDefinition=lambda kind: definition,
            CreateFeature=lambda data: fake_feature("RotaryMotor1", "AEMRotationalMotor"),
            GetMotionFeatures=lambda: [fake_feature("RotaryMotor1", "AEMRotationalMotor")],
            GetMotionFeaturesCount=lambda: 1,
        )
        selection_manager = SimpleNamespace(GetSelectedObject6=lambda mark, index: object(),
                                            _FlagAsMethod=lambda name: None)
        doc = SimpleNamespace(SelectionManager=selection_manager)
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "require_selection", return_value=1), \
                patch.object(sw_motion, "active_document", return_value=(None, doc)):
            payload = sw_motion.add_motion_motor(
                {"name": "Solve", "motor_type": "rotational", "direction": {"edges": [0]}, "speed": 30.0})
        self.assertFalse(payload["ok"], payload)


class MotionResultTests(unittest.TestCase):
    def test_triple_scales_si_values_and_survives_nothing(self):
        self.assertEqual(sw_motion._triple(SimpleNamespace(ArrayData=[1.0, -2.0, 0.5]), 1000.0), [1000.0, -2000.0, 500.0])
        self.assertIsNone(sw_motion._triple(None))
        self.assertIsNone(sw_motion._triple(SimpleNamespace(ArrayData=None)))

    def test_only_a_real_change_counts_as_motion(self):
        still = [{"time_sec": 0.0, "position_mm": [0.0, 0.0, 0.0]},
                 {"time_sec": 1.0, "position_mm": [0.0, 0.0, 0.0], "linear_velocity_mm_per_s": [0.0, 0.0, 0.0]}]
        moving = [{"time_sec": 0.0, "position_mm": [0.0, 0.0, 0.0], "linear_velocity_mm_per_s": [0.0, 0.0, 0.0]},
                  {"time_sec": 1.0, "position_mm": [0.0, 0.0, 0.0], "linear_velocity_mm_per_s": [0.0, -9810.0, 0.0]}]
        self.assertFalse(sw_motion._moved(still))
        self.assertFalse(sw_motion._moved([]))
        self.assertTrue(sw_motion._moved(moving))

    def test_sample_times_default_to_the_timeline(self):
        study = SimpleNamespace(GetDuration=lambda: 4.0)
        self.assertEqual(sw_motion._sample_times(study, None), [0.0, 2.0, 4.0])
        self.assertEqual(sw_motion._sample_times(SimpleNamespace(GetDuration=lambda: 0.0), None), [0.0])
        with self.assertRaises(RuntimeError):
            sw_motion._sample_times(study, [0.0, 5.0])

    def test_solve_reports_a_simulation_study_that_produced_no_motion(self):
        study = SimpleNamespace(Calculate=lambda: True, GetMotionFeaturesCount=lambda: 1)
        samples = [{"time_sec": 0.0, "position_mm": [0.0, 0.0, 0.0]},
                   {"time_sec": 1.0, "position_mm": [0.0, 0.0, 0.0]}]
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "_info", return_value={"type_code": 2, "type": "basic_motion"}), \
                patch.object(sw_motion, "_results", return_value=SimpleNamespace(IsOutOfDate=lambda: False)), \
                patch.object(sw_motion, "active_document", return_value=(None, None)), \
                patch.object(sw_motion, "_component", return_value=SimpleNamespace(Name2="block-1")), \
                patch.object(sw_motion, "_sample", return_value=samples), \
                patch.object(sw_motion, "_sample_times", return_value=[0.0, 1.0]):
            payload = sw_motion.solve_motion_study({"name": "Solve"})
        self.assertFalse(payload["ok"], payload)
        self.assertTrue(payload["data"]["native_accepted"])
        self.assertFalse(payload["data"]["out_of_date"])
        self.assertFalse(payload["data"]["motion_detected"])

    def test_solve_accepts_an_animation_that_does_not_move_components(self):
        study = SimpleNamespace(Calculate=lambda: True, GetMotionFeaturesCount=lambda: 0)
        samples = [{"time_sec": 0.0, "position_mm": [0.0, 0.0, 0.0]},
                   {"time_sec": 1.0, "position_mm": [0.0, 0.0, 0.0]}]
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "_info", return_value={"type_code": 1, "type": "animation"}), \
                patch.object(sw_motion, "_results", return_value=SimpleNamespace(IsOutOfDate=lambda: False)), \
                patch.object(sw_motion, "active_document", return_value=(None, None)), \
                patch.object(sw_motion, "_component", return_value=SimpleNamespace(Name2="block-1")), \
                patch.object(sw_motion, "_sample", return_value=samples), \
                patch.object(sw_motion, "_sample_times", return_value=[0.0, 1.0]):
            payload = sw_motion.solve_motion_study({"name": "Anim"})
        self.assertTrue(payload["ok"], payload)

    def test_solve_refuses_when_the_results_stay_out_of_date(self):
        study = SimpleNamespace(Calculate=lambda: True, GetMotionFeaturesCount=lambda: 0)
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "_info", return_value={"type_code": 1, "type": "animation"}), \
                patch.object(sw_motion, "_results", return_value=SimpleNamespace(IsOutOfDate=lambda: True)), \
                patch.object(sw_motion, "active_document", return_value=(None, None)), \
                patch.object(sw_motion, "_component", return_value=None):
            payload = sw_motion.solve_motion_study({"name": "Anim"})
        self.assertFalse(payload["ok"], payload)
        self.assertTrue(payload["data"]["out_of_date"])

    def test_solve_reports_a_missing_results_object(self):
        study = SimpleNamespace(Calculate=lambda: True, GetMotionFeaturesCount=lambda: 0)
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "_info", return_value={"type_code": 4, "type": "motion_analysis"}), \
                patch.object(sw_motion, "_results", return_value=None):
            payload = sw_motion.solve_motion_study({"name": "Analysis"})
        self.assertFalse(payload["ok"], payload)


class MotionAnimationTests(unittest.TestCase):
    def test_animation_duration_is_required_before_com(self):
        for args in ({"duration_sec": 0}, {"duration_sec": -2}, {"duration_sec": float("nan")}, {"duration_sec": 1, "start_time_sec": -1}):
            with self.subTest(args=args), patch.object(sw_motion, "_manager") as manager:
                with self.assertRaises(RuntimeError):
                    sw_motion.set_motion_study_animation({"name": "Anim", "action": "rotate_model", **args})
                manager.assert_not_called()

    def test_animation_timeline_must_cover_the_request(self):
        study = SimpleNamespace(CreateByRotateModel=lambda *args: True)
        with patch.object(sw_motion, "_manager"), patch.object(sw_motion, "_study", return_value=study), \
                patch.object(sw_motion, "_activate", return_value=True), \
                patch.object(sw_motion, "_info", return_value={"duration_sec": 2.0}):
            payload = sw_motion.set_motion_study_animation(
                {"name": "Anim", "action": "rotate_model", "duration_sec": 2.0, "start_time_sec": 3.0})
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["data"]["expected_end_sec"], 5.0)


class MotionExportTests(unittest.TestCase):
    def test_export_requires_a_matching_extension(self):
        with patch.object(sw_motion, "validated_output_path",
                          side_effect=lambda path, allowed, allow_overwrite=False: Path(path)), \
                patch.object(sw_motion, "_manager") as manager:
            with self.assertRaises(RuntimeError):
                sw_motion.export_motion_study_frames({"name": "Anim", "path": "anim.avi", "format": "png"})
            manager.assert_not_called()

    def test_export_rejects_an_unknown_format(self):
        with patch.object(sw_motion, "_manager") as manager:
            with self.assertRaises(RuntimeError):
                sw_motion.export_motion_study_frames({"name": "Anim", "path": "anim.xyz", "format": "xyz"})
            manager.assert_not_called()

    def test_frame_wait_returns_finished_files_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "anim.png"
            (root / "anim-0000.png").write_bytes(b"frame")
            (root / "anim-0001.png").write_bytes(b"frame")
            files = sw_motion._await_files(target, deadline_sec=0.0)
        self.assertEqual([path.name for path in files], ["anim-0000.png", "anim-0001.png"])


if __name__ == "__main__":
    unittest.main()
