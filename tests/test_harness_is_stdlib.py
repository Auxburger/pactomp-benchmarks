"""src/harness must run with the cluster python3 — standard library only.

A third-party import here breaks every cluster run, where there is no uv and no
virtualenv, and it would only fail once a job is already queued.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


HARNESS = Path(__file__).resolve().parents[1] / "src" / "harness"


def top_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


class HarnessDependencyTest(unittest.TestCase):
    def test_every_module_imports_only_the_standard_library(self) -> None:
        allowed = set(sys.stdlib_module_names) | {"harness"}
        offenders: dict[str, set[str]] = {}
        for path in sorted(HARNESS.rglob("*.py")):
            outside = top_level_imports(path) - allowed
            if outside:
                offenders[str(path.relative_to(HARNESS.parents[1]))] = outside
        self.assertEqual(offenders, {}, f"non-stdlib imports in src/harness: {offenders}")

    def test_the_check_actually_sees_the_modules(self) -> None:
        self.assertGreaterEqual(len(list(HARNESS.rglob("*.py"))), 10)


if __name__ == "__main__":
    unittest.main()
