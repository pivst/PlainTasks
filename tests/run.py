"""Run the standalone suite with Python 3.14: python tests/run.py."""

import importlib
import importlib.machinery
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Use Python 3.14, matching the Sublime Text 4215 plugin host")
    sys.path.insert(0, str(ROOT / "tests"))
    if "PlainTasks" not in sys.modules:
        package = types.ModuleType("PlainTasks")
        package.__path__ = [str(ROOT)]
        package.__spec__ = importlib.machinery.ModuleSpec(
            "PlainTasks", loader=None, is_package=True
        )
        sys.modules["PlainTasks"] = package
    try:
        import sublime  # noqa: F401
    except ImportError:
        from PlainTasks.tests.support.sublime_stub import install

        install()
    for module in ("APlainTasksCommon", "PlainTasksDates", "PlainTasks", "PlainTasksToHTML"):
        importlib.import_module(f"PlainTasks.{module}")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
