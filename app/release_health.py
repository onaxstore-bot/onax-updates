"""Release probe: compile sources and run offline tests. No external calls."""
import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True
for source in root.rglob('*.py'):
    compile(source.read_text(encoding='utf-8'), str(source), 'exec')
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=0).run(suite)
raise SystemExit(0 if result.wasSuccessful() and result.testsRun >= 145 else 1)
