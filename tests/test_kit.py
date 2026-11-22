"""`pbidriver setup` / doctor helpers: config merging, AGENTS.md block, skill copy. No Power BI needed."""
import json
import sys
from pathlib import Path

import pytest

from pbidriver import kit

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_tools(monkeypatch):
    """A machine with neither uv nor Node nor the VS Code extension."""
    monkeypatch.setattr(kit, "_which", lambda name: None)
    monkeypatch.setattr(kit, "modeling_exes", lambda: [])


def test_server_commands(monkeypatch, no_tools):
    assert kit.pbidriver_server() == {"command": sys.executable, "args": ["-m", "pbidriver", "mcp"]}
    assert kit.modeling_server() is None
    monkeypatch.setattr(kit, "_which", lambda name: f"C:/bin/{name}.exe")
    assert kit.pbidriver_server() == {"command": "uvx", "args": ["pbidriver@latest", "mcp"]}
    npx = kit.modeling_server()
    assert "@microsoft/powerbi-modeling-mcp@latest" in npx["args"] and "--start" in npx["args"]
    if sys.platform == "win32":
        assert npx["command"] == "cmd" and npx["args"][:2] == ["/c", "npx"]
    with pytest.raises(ValueError):
        kit.modeling_server("exe")  # no extension installed


def test_setup_writes_everything_once(tmp_path, monkeypatch, no_tools):
    monkeypatch.setattr(kit, "modeling_server", lambda mode="auto": {"command": "npx", "args": [
        "-y", "@microsoft/powerbi-modeling-mcp@latest", "--start"]})
    out = kit.setup(str(tmp_path), ["all"], runner="python")
    for client in kit.CLIENTS:
        assert out["files"][client]["servers"]["pbidriver"] == "added"
    claude = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert claude["pbidriver"]["args"][-1] == "mcp" and "powerbi-modeling" in claude
    vscode = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())["servers"]
    assert vscode["pbidriver"]["type"] == "stdio"
    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.pbidriver]" in toml and "[mcp_servers.powerbi-modeling]" in toml
    assert kit._read_servers(tmp_path / ".codex" / "config.toml", "mcp_servers")["pbidriver"]
    agents = (tmp_path / "AGENTS.md").read_text()
    assert agents.count(kit.BLOCK_START) == 1 and "pbi_refresh sync=true" in agents
    assert (tmp_path / "CLAUDE.md").read_text().strip() == "@AGENTS.md"
    assert (tmp_path / ".claude" / "skills" / "powerbi-builder" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "skills" / "powerbi-builder" / "references" / "visuals.md").is_file()
    assert (tmp_path / ".github" / "skills" / "powerbi-builder" / "SKILL.md").is_file()

    again = kit.setup(str(tmp_path), ["all"], runner="python")
    assert again["files"]["claude"]["servers"]["pbidriver"].startswith("kept existing")
    assert again["files"]["AGENTS.md"] == "unchanged" and again["files"]["claude_skill"] == "unchanged"
    assert (tmp_path / "AGENTS.md").read_text().count(kit.BLOCK_START) == 1
    assert (tmp_path / ".codex" / "config.toml").read_text().count("[mcp_servers.pbidriver]") == 1


def test_setup_keeps_what_is_already_there(tmp_path, no_tools):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "other": {"command": "x"},
        "pbi-model": {"command": "C:/ext/powerbi-modeling-mcp.exe", "args": ["--start"]}}}))
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nBe nice.\n")
    (tmp_path / "CLAUDE.md").write_text("# Claude\n")
    out = kit.setup(str(tmp_path), ["claude"], runner="python", modeling="none")
    servers = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"other", "pbi-model", "pbidriver"}
    assert out["files"]["AGENTS.md"] == "added"
    agents = (tmp_path / "AGENTS.md").read_text()
    assert agents.startswith("# House rules") and kit.BLOCK_END in agents
    assert (tmp_path / "CLAUDE.md").read_text() == "# Claude\n\n@AGENTS.md\n"

    # An edited block is replaced in place; text after it survives.
    text = agents.replace("## Power BI", "## OLD").replace(kit.BLOCK_END, kit.BLOCK_END + "\n\nAfter.")
    (tmp_path / "AGENTS.md").write_text(text)
    assert kit._write_block(tmp_path / "AGENTS.md", dry=False) == "updated"
    final = (tmp_path / "AGENTS.md").read_text()
    assert "## OLD" not in final and final.rstrip().endswith("After.") and final.count(kit.BLOCK_START) == 1


def test_modeling_server_already_configured_is_detected(tmp_path, monkeypatch, no_tools):
    monkeypatch.setattr(kit, "modeling_server", lambda mode="auto": {"command": "npx", "args": [
        "-y", "@microsoft/powerbi-modeling-mcp@latest", "--start"]})
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "powerbi-authoring-local": {"command": "npx", "args": ["-y", "@microsoft/powerbi-modeling-mcp@latest"]}}}))
    out = kit.setup(str(tmp_path), ["claude"], runner="python")
    assert out["files"]["claude"]["servers"]["powerbi-modeling"] == "kept existing 'powerbi-authoring-local'"
    out = kit.setup(str(tmp_path), ["claude"], runner="python", force=True)
    assert out["files"]["claude"]["servers"]["powerbi-modeling"] == "added"


def test_dry_run_writes_nothing(tmp_path, no_tools):
    out = kit.setup(str(tmp_path), ["all"], runner="python", modeling="none", dry_run=True)
    assert out["dry_run"] and list(tmp_path.iterdir()) == []


def test_invalid_json_config_is_reported(tmp_path, no_tools):
    (tmp_path / ".mcp.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        kit.setup(str(tmp_path), ["claude"], runner="python", modeling="none")


def test_plugin_copy_of_the_skill_matches_the_package():
    """plugins/pbidriver/skills is what Claude Code's plugin installs; it must equal the packaged skill."""
    src = kit.skill_source()
    dst = ROOT / "plugins" / "pbidriver" / "skills" / kit.SKILL_NAME
    files = sorted(p.relative_to(src) for p in src.rglob("*") if p.is_file())
    assert files and files == sorted(p.relative_to(dst) for p in dst.rglob("*") if p.is_file())
    for rel in files:
        assert (src / rel).read_bytes() == (dst / rel).read_bytes(), f"{rel} differs: run scripts/sync_skill.py"
