"""`pbidriver doctor` and `pbidriver setup`: get a machine and a project ready for agent-driven Power BI work
with pbidriver (report UI and PBIR authoring) plus Microsoft's Power BI Modeling MCP (the semantic model)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pbidriver import __version__

MODELING_NPM = "@microsoft/powerbi-modeling-mcp"
MODELING_NAME = "powerbi-modeling"
SKILL_NAME = "powerbi-builder"
CLIENTS = ("claude", "vscode", "cursor", "codex")
BLOCK_START = "<!-- pbidriver:start -->"
BLOCK_END = "<!-- pbidriver:end -->"

AGENTS_BLOCK = f"""{BLOCK_START}
## Power BI: pbidriver + Power BI Modeling MCP

Power BI reports in this project are built by agents with two MCP servers:

- **{MODELING_NAME}** (Microsoft's Power BI Modeling MCP): the semantic model. Tables, columns, measures,
  relationships, and DAX validation, applied to the model open in Power BI Desktop.
- **pbidriver**: everything else. Open Power BI Desktop, create PBIP projects, add pages and visuals,
  screenshots (returned as images), the numbers behind visuals, clicks/slicers/keys, dialogs, refresh, save.

Before building or changing a report, call the `pbi_guide` tool (or read
`.claude/skills/{SKILL_NAME}/SKILL.md`). The short version:

1. `pbi_new` (folder, name, open=true) or `pbi_launch` an existing .pbip. A .pbix must become a PBIP first:
   `pbi_save as=<file>.pbip`.
2. `pbi_instances` gives `model_port`. Connect the Modeling MCP to `localhost:<model_port>`, create the model,
   then `pbi_refresh sync=true` (Power BI's refresh skips tables it hasn't re-read from the project).
3. `pbi_add_visual` with `shot=true` to see each visual as you add it.
4. Verify with `pbi_shot`, `pbi_read` and `pbi_dax`, handle anything in `alerts`, then `pbi_save`.

Never edit the TMDL files of a project while Power BI has it open: model changes go through the Modeling MCP
and reach the files on `pbi_save`. Without MCP, the same commands exist as a CLI: `pbidriver <command> --help`.
{BLOCK_END}
"""


# --------------------------------------------------------------------------- discovery

def _which(name: str) -> str | None:
    return shutil.which(name)


def modeling_exes() -> list[Path]:
    """powerbi-modeling-mcp.exe from the VS Code / VS Code Insiders / Cursor extension, newest first."""
    home = Path.home()
    found = []
    for root in (".vscode", ".vscode-insiders", ".cursor"):
        for ext in (home / root / "extensions").glob("analysis-services.powerbi-modeling-mcp-*"):
            exe = ext / "server" / "powerbi-modeling-mcp.exe"
            if exe.is_file():
                found.append(exe)

    def version(p: Path):
        v = p.parent.parent.name.split("powerbi-modeling-mcp-", 1)[-1].split("-")[0]
        return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))

    return sorted(found, key=version, reverse=True)


def _npx_command(args: list[str]) -> dict:
    # npx is npx.cmd on Windows; MCP clients start servers without a shell, so go through cmd /c.
    if sys.platform == "win32":
        return {"command": "cmd", "args": ["/c", "npx", *args]}
    return {"command": "npx", "args": args}


def pbidriver_server(runner: str = "auto") -> dict:
    """How an MCP client should start the pbidriver server."""
    if runner == "auto":
        runner = "uvx" if _which("uvx") else "npx" if _which("npx") else "python"
    if runner == "uvx":
        return {"command": "uvx", "args": ["pbidriver@latest", "mcp"]}
    if runner == "npx":
        return _npx_command(["-y", "pbidriver@latest", "mcp"])
    if runner == "python":
        return {"command": sys.executable, "args": ["-m", "pbidriver", "mcp"]}
    raise ValueError(f"Unknown runner {runner!r}: use auto, uvx, npx or python")


def modeling_server(mode: str = "auto") -> dict | None:
    """How an MCP client should start Microsoft's Power BI Modeling MCP (None: not available)."""
    if mode == "none":
        return None
    exes = modeling_exes()
    if mode == "auto":
        mode = "npx" if _which("npx") else "exe" if exes else "none"
    if mode == "npx":
        return _npx_command(["-y", f"{MODELING_NPM}@latest", "--start"])
    if mode == "exe":
        if not exes:
            raise ValueError("The Power BI Modeling MCP VS Code extension isn't installed, so there is no exe to use. "
                             "Install Node.js (for npx) or the extension 'analysis-services.powerbi-modeling-mcp'.")
        return {"command": str(exes[0]), "args": ["--start"]}
    if mode == "none":
        return None
    raise ValueError(f"Unknown modeling mode {mode!r}: use auto, npx, exe or none")


def _is_modeling(cfg: dict) -> bool:
    text = " ".join([str(cfg.get("command", "")), *map(str, cfg.get("args", []) or [])]).lower()
    return "powerbi-modeling-mcp" in text


def _is_pbidriver(cfg: dict) -> bool:
    text = " ".join([str(cfg.get("command", "")), *map(str, cfg.get("args", []) or [])]).lower()
    return "pbidriver" in text and "mcp" in text


def _pbi_desktop() -> dict:
    out: dict = {"installed": False}
    try:
        from pbidriver.cli import find_pbi_exe

        out["exe"] = str(find_pbi_exe())
        out["installed"] = True
    except Exception:  # noqa: BLE001
        return out
    if sys.platform == "win32":
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                                "(Get-AppxPackage -Name Microsoft.MicrosoftPowerBIDesktop).Version"],
                               capture_output=True, text=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.stdout.strip():
                out["version"], out["edition"] = r.stdout.strip().splitlines()[0], "Microsoft Store"
        except Exception:  # noqa: BLE001
            pass
        if "version" not in out and out["exe"].lower().endswith("pbidesktop.exe"):
            try:
                import win32api

                info = win32api.GetFileVersionInfo(out["exe"], "\\")
                ms, ls = info["FileVersionMS"], info["FileVersionLS"]
                out["version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
                out["edition"] = "installer"
            except Exception:  # noqa: BLE001
                pass
    return out


# --------------------------------------------------------------------------- doctor

def doctor(project: str | None = None) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail, fix: str | None = None, required: bool = True) -> None:
        item = {"check": name, "ok": bool(ok), "detail": detail}
        if not ok and fix:
            item["fix"] = fix
        if not required:
            item["optional"] = True
        checks.append(item)

    check("windows", sys.platform == "win32", sys.platform,
          "pbidriver drives Power BI Desktop, which runs on Windows only.")
    check("python", sys.version_info >= (3, 9), f"{sys.version.split()[0]} at {sys.executable}",
          "Use Python 3.9 or later.")
    check("pbidriver", True, __version__)

    pbi = _pbi_desktop()
    check("power-bi-desktop", pbi["installed"],
          {k: v for k, v in pbi.items() if k != "installed"} or "not found",
          "Install Power BI Desktop (Microsoft Store or https://aka.ms/pbidesktop), or set PBI_DESKTOP_EXE.")

    try:
        from pbidriver import bridge

        insts = bridge.instances()
    except Exception as e:  # noqa: BLE001
        insts, err = [], f"{type(e).__name__}: {e}"
        check("instances", False, err)
    else:
        check("instances", True, [{k: i.get(k) for k in ("pid", "file", "devtools_port", "bridge", "model_port")}
                                  for i in insts] or "none running (start one with `pbidriver launch <file>`)")
        if insts:
            check("desktop-bridge", any(i.get("bridge") for i in insts),
                  "available" if any(i.get("bridge") for i in insts) else "not reported by any running instance",
                  "Update Power BI Desktop (the Desktop Bridge ships with June 2026 and later). Without it, "
                  "reload/save confirmation and Bridge captures are unavailable; DevTools features still work.",
                  required=False)

    exes = modeling_exes()
    npx = _which("npx")
    check("power-bi-modeling-mcp", bool(exes or npx),
          {"vscode_extension_exe": str(exes[0]) if exes else None, "npx": npx,
           "will_run": modeling_server("auto")},
          "Install Node.js (then the Modeling MCP runs with npx) or the VS Code extension "
          "'analysis-services.powerbi-modeling-mcp'.")
    check("uv", bool(_which("uvx")), _which("uvx") or "not found",
          "Optional: install uv (https://docs.astral.sh/uv/) so MCP clients can run `uvx pbidriver@latest mcp`.",
          required=False)
    check("mcp-server-command", True, pbidriver_server("auto"))

    root = Path(project or ".").resolve()
    configs = {}
    for client, (rel, key) in CONFIG_FILES.items():
        path = root / rel
        if not path.is_file():
            configs[client] = "missing"
            continue
        servers = _read_servers(path, key)
        configs[client] = {"file": str(path),
                           "pbidriver": any(_is_pbidriver(c) for c in servers.values()),
                           "modeling": any(_is_modeling(c) for c in servers.values())}
    skill = root / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
    agents = root / "AGENTS.md"
    has_block = agents.is_file() and BLOCK_START in agents.read_text(encoding="utf-8", errors="replace")
    configured = any(isinstance(v, dict) and v["pbidriver"] for v in configs.values())
    check("project-setup", configured and has_block,
          {"folder": str(root), "mcp_configs": configs, "agents_md": has_block, "skill": skill.is_file()},
          f"Run `pbidriver setup` in {root} to write MCP configs, AGENTS.md and the {SKILL_NAME} skill.",
          required=False)

    problems = [c["check"] for c in checks if not c["ok"] and not c.get("optional")]
    return {"ready": not problems, "problems": problems, "checks": checks}


# --------------------------------------------------------------------------- setup

CONFIG_FILES = {  # client: (file relative to the project, key holding the servers)
    "claude": (".mcp.json", "mcpServers"),
    "vscode": (".vscode/mcp.json", "servers"),
    "cursor": (".cursor/mcp.json", "mcpServers"),
    "codex": (".codex/config.toml", "mcp_servers"),
}


def _read_servers(path: Path, key: str) -> dict:
    if path.suffix == ".toml":
        text = path.read_text(encoding="utf-8")
        try:
            import tomllib
        except ImportError:  # Python < 3.11: each [key.name] table's raw text is enough to recognize servers
            out, name = {}, None
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("["):
                    name = s.strip("[]").split(".", 1)[1].strip('"') if s.startswith(f"[{key}.") else None
                    if name:
                        out[name] = {"command": "", "args": []}
                elif name:
                    out[name]["command"] += " " + s
            return out
        return tomllib.loads(text).get(key) or {}
    try:
        return (json.loads(path.read_text(encoding="utf-8-sig") or "{}").get(key) or {})
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON ({e}); fix it or move it away, then run setup again.") from e


def _toml_value(v) -> str:
    return json.dumps(v) if not isinstance(v, list) else "[" + ", ".join(json.dumps(x) for x in v) + "]"


def _write_config(path: Path, key: str, wanted: dict, client: str, force: bool, dry: bool) -> dict:
    existing = _read_servers(path, key) if path.is_file() else {}
    actions = {}
    add = {}
    for name, cfg in wanted.items():
        same_kind = [n for n, c in existing.items() if (_is_modeling(c) if name == MODELING_NAME else _is_pbidriver(c))]
        if same_kind and not force:
            actions[name] = f"kept existing '{same_kind[0]}'"
            continue
        if name in existing and not force:
            actions[name] = f"kept: a different server is already named '{name}' (use --force to replace)"
            continue
        add[name] = cfg
        actions[name] = "replaced" if name in existing else "added"
    if add and not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".toml":
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            for name, cfg in add.items():
                header = f"[{key}.{name}]"
                if header in text:  # --force: drop the old table first
                    start = text.index(header)
                    nxt = text.find("\n[", start + 1)
                    text = text[:start] + (text[nxt + 1:] if nxt != -1 else "")
                body = "\n".join(f"{k} = {_toml_value(v)}" for k, v in cfg.items())
                text = text.rstrip() + ("\n\n" if text.strip() else "") + f"{header}\n{body}\n"
            path.write_text(text, encoding="utf-8")
        else:
            data = json.loads(path.read_text(encoding="utf-8-sig") or "{}") if path.is_file() else {}
            servers = data.setdefault(key, {})
            for name, cfg in add.items():
                servers[name] = ({"type": "stdio", **cfg} if client == "vscode" else cfg)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"file": str(path), "servers": actions}


def _write_block(path: Path, dry: bool) -> str:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BLOCK_START in text and BLOCK_END in text:
        start, end = text.index(BLOCK_START), text.index(BLOCK_END) + len(BLOCK_END)
        new = text[:start] + AGENTS_BLOCK.rstrip("\n") + text[end:]
        action = "updated" if new != text else "unchanged"
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + AGENTS_BLOCK
        action = "added" if text else "created"
    if not dry and new != text:
        path.write_text(new, encoding="utf-8")
    return action


def skill_source() -> Path:
    return Path(__file__).with_name("skill") / SKILL_NAME


def _copy_skill(dest: Path, dry: bool) -> str:
    src = skill_source()
    files = [p for p in src.rglob("*") if p.is_file()]
    changed = [p for p in files
               if not (dest / p.relative_to(src)).is_file() or (dest / p.relative_to(src)).read_bytes() != p.read_bytes()]
    if not changed:
        return "unchanged"
    existed = (dest / "SKILL.md").is_file()
    if not dry:
        for p in changed:
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
    return "updated" if existed else "added"


def setup(folder: str = ".", clients: list[str] | None = None, runner: str = "auto", modeling: str = "auto",
          force: bool = False, dry_run: bool = False) -> dict:
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError(f"No such folder: {root}")
    clients = list(clients or ["claude", "vscode", "cursor"])
    if "all" in clients:
        clients = list(CLIENTS)
    bad = [c for c in clients if c not in CLIENTS]
    if bad:
        raise ValueError(f"Unknown client(s) {bad}; choose from {', '.join(CLIENTS)} or all")

    ours = pbidriver_server(runner)
    model = modeling_server(modeling)
    notes = []
    if model is None:
        notes.append("The Power BI Modeling MCP was not configured: install Node.js or the VS Code extension "
                     "'analysis-services.powerbi-modeling-mcp', then run setup again.")
    out: dict = {"folder": str(root), "dry_run": dry_run, "pbidriver_server": ours, "modeling_server": model,
                 "files": {}}
    for client in clients:
        rel, key = CONFIG_FILES[client]
        wanted = {"pbidriver": ours}
        if model:
            if client == "vscode" and modeling_exes() and modeling != "npx":
                notes.append("VS Code: the Power BI Modeling MCP extension registers its own server, so "
                             ".vscode/mcp.json only gets pbidriver.")
            else:
                wanted[MODELING_NAME] = model
        out["files"][client] = _write_config(root / rel, key, wanted, client, force, dry_run)

    out["files"]["AGENTS.md"] = _write_block(root / "AGENTS.md", dry_run)
    if "claude" in clients:  # Claude Code reads CLAUDE.md, not AGENTS.md: import it
        claude_md = root / "CLAUDE.md"
        text = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
        if "@AGENTS.md" in text or BLOCK_START in text:
            out["files"]["CLAUDE.md"] = "unchanged"
        else:
            if not dry_run:
                claude_md.write_text((text.rstrip() + "\n\n" if text.strip() else "") + "@AGENTS.md\n",
                                     encoding="utf-8")
            out["files"]["CLAUDE.md"] = "added @AGENTS.md" if text else "created (imports AGENTS.md)"
        out["files"]["claude_skill"] = _copy_skill(root / ".claude" / "skills" / SKILL_NAME, dry_run)
    if "vscode" in clients:
        out["files"]["copilot_skill"] = _copy_skill(root / ".github" / "skills" / SKILL_NAME, dry_run)

    notes.append("Restart your agent (or reload its MCP servers) so it picks up the new servers.")
    if model:
        notes.append("First use of the Modeling MCP may ask you to accept Microsoft's EULA and to confirm writes; "
                     "that's expected.")
    out["notes"] = notes
    out["next"] = "Ask your agent to build a report, e.g. \"Build a sales report from data/sales.csv\". " \
                  "It will find the pbi_guide tool and the powerbi-builder skill."
    return out
