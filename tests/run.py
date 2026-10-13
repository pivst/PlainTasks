"""Run outside the editor: python tests/run.py."""

import importlib
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
sys.path.insert(0, str(root / 'tests'))

# Match Sublime's package-module loading even if the checkout has another name.
package = importlib.import_module(root.name)
sys.modules['PlainTasks'] = package

try:
    import sublime  # noqa: F401
except ImportError:
    from PlainTasks.tests.support.sublime_stub import install
    install()

for module in ('APlainTasksCommon', 'PlainTasksDates', 'PlainTasks', 'PlainTasksToHTML', 'plist_parser'):
    importlib.import_module(f'PlainTasks.{module}')

suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
