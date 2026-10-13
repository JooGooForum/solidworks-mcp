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

"""Component insertion has to leave the assembly as the active document.

Inserting a part that SOLIDWORKS has to open first activates that part, so the
insertion tool would otherwise hand the next tool a part document.
"""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from solidworks_mcp import sw_assembly


class FakeApplication:
    def __init__(self, opens_the_part=True, activates=True):
        self.assembly = SimpleNamespace(GetTitle="Assembly1")
        self.part = SimpleNamespace(GetTitle="InstalledMotionPart.SLDPRT")
        self.ActiveDoc = self.assembly
        self.opens_the_part = opens_the_part
        self.activates = activates
        self.activation_calls = []

    def OpenDoc6(self, *arguments):
        if self.opens_the_part:
            self.ActiveDoc = self.part
        return self.part

    def ActivateDoc3(self, title, *arguments):
        self.activation_calls.append(title)
        if self.activates and title == self.assembly.GetTitle:
            self.ActiveDoc = self.assembly
            return True
        return False


class InsertComponentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.part_path = Path(self.folder.name) / "part.SLDPRT"
        self.part_path.write_bytes(b"")
        self.component = SimpleNamespace(Name2="part-1")

    def insert(self, app):
        app.assembly.AddComponent5 = lambda *arguments: self.component
        with patch.object(sw_assembly, "require_assembly", return_value=(app, app.assembly)), \
                patch.object(sw_assembly, "rebuild"):
            return sw_assembly.insert_component({"path": str(self.part_path)})

    def test_the_assembly_is_reactivated_after_inserting_a_closed_part(self):
        app = FakeApplication()
        payload = self.insert(app)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["active_document"], "Assembly1")
        self.assertEqual(app.activation_calls, ["Assembly1"])

    def test_an_already_active_assembly_is_not_reactivated(self):
        app = FakeApplication(opens_the_part=False)
        payload = self.insert(app)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["active_document"], "Assembly1")
        self.assertEqual(app.activation_calls, [])

    def test_a_failed_reactivation_is_reported_with_the_inserted_component(self):
        app = FakeApplication(activates=False)
        payload = self.insert(app)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["data"]["component"], "part-1")
        self.assertEqual(payload["data"]["active_document"], "InstalledMotionPart.SLDPRT")
        self.assertIn("left another document active", payload["message"])
