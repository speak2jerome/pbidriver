"""Copy the packaged powerbi-builder skill (pbidriver/skill/) into the Claude Code plugin (plugins/pbidriver/skills/).

The package copy is the source: `pbidriver setup` and the MCP server's pbi_guide tool read it. The plugin copy
exists because a Claude Code plugin can only ship files inside its own folder. tests/test_kit.py fails when the
two differ.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pbidriver" / "skill" / "powerbi-builder"
DST = ROOT / "plugins" / "pbidriver" / "skills" / "powerbi-builder"

if DST.exists():
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)
print(f"copied {sum(1 for p in DST.rglob('*') if p.is_file())} files to {DST.relative_to(ROOT)}")
