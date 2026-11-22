import sys
from pathlib import Path

# Run the tests against the modules in this checkout without installing them.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
