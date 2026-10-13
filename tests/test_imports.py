# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Keep the package importable however it is started.

An absolute ``from sw_core import ...`` inside a tool body only fails when that
tool is called, so the offline suite stayed green while `draw_spline`,
`list_mates` and three drawing tools were dead on a real install (issue #3).
These checks import every module as part of the package and refuse the absolute
sibling import that caused it.
"""

import importlib
import pkgutil
from pathlib import Path
import re
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / "solidworks_mcp"
SIBLING = re.compile(r"^\s*(?:from|import)\s+sw_[a-z_]+\b")


class PackageImportTests(unittest.TestCase):
    def test_every_module_imports_as_part_of_the_package(self):
        names = sorted(module.name for module in pkgutil.iter_modules([str(PACKAGE)]))
        self.assertIn("sw_core", names)
        for name in names:
            with self.subTest(module=name):
                importlib.import_module(f"solidworks_mcp.{name}")

    def test_no_absolute_sibling_imports(self):
        offenders = []
        for path in sorted(PACKAGE.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if SIBLING.match(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_the_tools_from_the_reported_modules_are_registered(self):
        from solidworks_mcp import server

        names = {tool.name for tool in server.TOOLS}
        for tool in ("draw_spline", "list_mates", "set_drawing_view", "insert_section_view",
                     "insert_detail_view"):
            self.assertIn(tool, names)


if __name__ == "__main__":
    unittest.main()
