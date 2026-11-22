"""pbidriver as an MCP server (stdio): every pbidriver command is a tool, screenshots come back as images.

    pbidriver mcp            (usually started by the MCP client, e.g. `uvx pbidriver mcp`)

The tools are generated from the CLI's own argument definitions, so the CLI and the MCP server can't
drift apart. Each call runs the CLI in a child process (Playwright's sync API can't run inside a server
event loop, and a crashed command can't take the server down), one call at a time because they all
drive the same Power BI window. The protocol layer is a small JSON-RPC 2.0 implementation over
newline-delimited stdio, so the server has no dependencies beyond pbidriver's own.
"""
from __future__ import annotations

import argparse
import base64
import functools
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from pbidriver import __version__

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PREFIX = "pbi_"
NOT_TOOLS = {"mcp", "setup"}  # commands that make no sense as tools
MAX_IMAGES = 8
MAX_IMAGE_SIDE = 2000
MAX_IMAGE_BYTES = 3_500_000

READ_ONLY = {"instances", "status", "pages", "alerts", "visuals", "inventory", "shot", "read", "dax", "model",
             "perf", "layout", "doctor", "wait", "hover"}
DESTRUCTIVE = {"close", "remove-visual"}

# Guidance an agent needs that doesn't fit in argparse help (which is written for a terminal).
NOTES = {
    "launch": "Opens a .pbix/.pbip/.pbit in a NEW Power BI Desktop window with DevTools on `port`. "
              "Every UI tool (shot, read, click, slicer, ...) needs an instance started this way. Returns when the "
              "report has loaded, or early with `alerts` when a dialog blocks loading (answer it with pbi_dialog). "
              "Give each instance its own port.",
    "instances": "Every running Power BI Desktop. `model_port` is the instance's Analysis Services port: the "
                 "Power BI Modeling MCP connects to it (connection string `Data Source=localhost:<model_port>`).",
    "status": "Quick health check of one instance: file, current page, unsaved changes, blocking dialogs.",
    "shot": "Returns the capture as an image. Use `annotate` to see each visual's index (the `visual` parameter "
            "of other tools), `visual` for one visual, `view` for the Table/Model/DAX/TMDL views.",
    "read": "The numbers behind visuals as JSON (chart points, card values, table/matrix rows, slicer items). "
            "Compare with pbi_dax to verify a visual shows what the model says.",
    "dax": "Run a DAX query (EVALUATE ...) against the open model and get rows back.",
    "model": "Tables, columns, measures (with expressions) and relationships of the open model.",
    "new": "Creates a blank PBIP project (PBIR report + empty TMDL model) in `folder`. With open=true it is "
           "launched right away. Build the model with the Power BI Modeling MCP, then add visuals with "
           "pbi_add_visual.",
    "layout": "Pages and visuals as stored in the PBIR files: ids (for remove_visual), types, positions, fields.",
    "add-page": "Adds a page to the PBIR files. Set reload=true to show it in Power BI.",
    "add-visual": "Adds a visual to the PBIR files of the open (or `project`) PBIP. Fields are checked against the "
                  "live model, so create tables and measures first. Field syntax: Table[Column], [Measure], "
                  "'My Table'[Column], or Sum/Avg/Min/Max/Count/DistinctCount/Median(Table[Column]). Prefix a role: "
                  "Category=Sales[Region], Y=[Total Sales]; without one the field goes to the first fitting role. "
                  "Use shot=true to reload and see the result. Run pbi_guide topic=visuals for every type's roles.",
    "remove-visual": "Deletes a visual (id from pbi_layout) from the PBIR files.",
    "reload": "Reloads a PBIP from disk through the Desktop Bridge. After editing report files, use "
              "report_only=true: it keeps model changes made through the Modeling MCP that aren't saved yet. A full "
              "reload re-reads the model from disk and DISCARDS unsaved model changes, so pbi_save first.",
    "save": "Saves the open file. as=<path>.pbip converts a .pbix into a PBIP project (needed for add_visual). "
            "Model changes made with the Modeling MCP are written to the TMDL files on save.",
    "refresh": "Home > Refresh: reloads data for every table and waits. After creating or changing tables with the "
               "Power BI Modeling MCP use sync=true (saves, reloads the project from disk, refreshes, saves): Power "
               "BI's refresh skips tables it hasn't read from the project. Returns refreshed=false with the error text "
               "when a source fails; close that dialog with pbi_dialog click=Close.",
    "close": "Closes the Power BI window. With unsaved changes pass discard=true or save=true.",
    "dialog": "Reads the dialog blocking Power BI (any kind), presses a button (click=...), or captures it.",
    "alerts": "Dialogs, message banners and visuals showing an error right now. Other tools return the same "
              "`alerts` key whenever something needs attention.",
    "click": "Clicks inside a visual (`visual` + `text` or `at`), a view, or a page point. For data points prefer "
             "pbi_read to find them, then click by text.",
    "slicer": "Reads a slicer's items and selection, or selects values / clears it.",
    "doctor": "Checks the machine: Power BI Desktop, Desktop Bridge, the Power BI Modeling MCP, Node/uv, and how "
              "this server is run. Start here when something doesn't work.",
}

GUIDE_TOPICS = {
    "workflow": "SKILL.md",
    "visuals": "references/visuals.md",
    "modeling-mcp": "references/modeling-mcp.md",
    "pbir": "references/pbir.md",
    "troubleshooting": "references/troubleshooting.md",
}

INSTRUCTIONS = """\
pbidriver drives Power BI Desktop for you: launch reports, see them (screenshots come back as images), read the
numbers behind visuals, click/slice/type, answer dialogs, run DAX, and author report pages and visuals in PBIP
(PBIR) projects. It pairs with Microsoft's Power BI Modeling MCP (tools like connection_operations,
table_operations, measure_operations), which edits the semantic model. Model = Modeling MCP; report pages,
visuals and everything you see = pbidriver.

Build a report:
1. pbi_new folder=... name=... open=true    (or pbi_launch an existing .pbip; convert a .pbix with pbi_save as=...)
2. pbi_instances -> model_port. Modeling MCP: connection_operations Connect to `localhost:<model_port>`, then
   create tables (M partitions), columns, measures, relationships. Then pbi_refresh sync=true to load data.
3. pbi_add_visual type=... field=[...] shot=true   (repeat; pbi_layout lists what is there)
4. Verify: pbi_shot, pbi_read, pbi_dax; fix anything in `alerts`.
5. pbi_save. Never hand-edit TMDL files of a project that is open in Power BI.

Call pbi_guide for the full workflow, visual types and roles, Modeling MCP recipes, and troubleshooting.
Every result is JSON with ok=true/false; read `alerts` and `next` when present.
"""


# --------------------------------------------------------------------------- tool definitions

@functools.lru_cache(maxsize=1)
def _commands() -> dict[str, tuple[argparse.ArgumentParser, str]]:
    from pbidriver.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {c.dest: c.help or "" for c in sub._choices_actions}
    return {name: (p, helps.get(name, "")) for name, p in sub.choices.items() if name not in NOT_TOOLS}


def _prop_name(action: argparse.Action) -> str:
    if not action.option_strings:
        return action.dest
    return max(action.option_strings, key=len).lstrip("-").replace("-", "_")


def _tool_args(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    return [a for a in parser._actions
            if not isinstance(a, (argparse._HelpAction, argparse._VersionAction)) and a.dest != argparse.SUPPRESS]


def _schema(action: argparse.Action) -> dict:
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        s: dict = {"type": "boolean"}
    else:
        base = {int: "integer", float: "number"}.get(action.type, "string")
        item: dict = {"type": base}
        if action.choices:
            item["enum"] = list(action.choices)
        many = isinstance(action, argparse._AppendAction) or action.nargs in ("+", "*")
        s = {"type": "array", "items": item} if many else dict(item)
    if action.help:
        s["description"] = action.help.replace("%%", "%")
    if action.default not in (None, False, argparse.SUPPRESS) and not isinstance(action.default, list):
        s["default"] = action.default
    return s


def _exclusive_note(parser: argparse.ArgumentParser) -> str:
    groups = [g for g in parser._mutually_exclusive_groups if len(g._group_actions) > 1]
    return " ".join("Use at most one of: " + ", ".join(_prop_name(a) for a in g._group_actions) + "."
                    for g in groups)


def tool_list() -> list[dict]:
    tools = []
    for name, (parser, help_text) in _commands().items():
        props, required = {}, []
        for action in _tool_args(parser):
            prop = _prop_name(action)
            props[prop] = _schema(action)
            if (not action.option_strings and action.nargs not in ("?", "*")) or action.required:
                required.append(prop)
        desc = NOTES.get(name) or (help_text[:1].upper() + help_text[1:] + ".")
        extra = _exclusive_note(parser)
        tool = {
            "name": PREFIX + name.replace("-", "_"),
            "title": f"Power BI: {help_text}" if help_text else name,
            "description": f"{desc} {extra}".strip(),
            "inputSchema": {"type": "object", "properties": props, "additionalProperties": False,
                            **({"required": required} if required else {})},
            "annotations": {"readOnlyHint": name in READ_ONLY, "destructiveHint": name in DESTRUCTIVE,
                            "openWorldHint": False},
        }
        tools.append(tool)
    tools.append({
        "name": PREFIX + "guide",
        "title": "Power BI: how to build reports with pbidriver and the Power BI Modeling MCP",
        "description": "Read this first when building or changing a Power BI report. Topics: workflow (default), "
                       "visuals (types, roles, field syntax), modeling-mcp (connect, tables from CSV/SQL, measures, "
                       "relationships), pbir (report file format), troubleshooting.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "topic": {"type": "string", "enum": list(GUIDE_TOPICS), "default": "workflow"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    })
    return tools


def build_argv(command: str, arguments: dict) -> tuple[list[str], str | None]:
    """CLI argv (and stdin text) for a tool call. Options use --flag=value so values may start with '-'."""
    parser = _commands()[command][0]
    actions = {_prop_name(a): a for a in _tool_args(parser)}
    unknown = sorted(set(arguments) - set(actions))
    if unknown:
        raise ValueError(f"Unknown argument(s) for {PREFIX}{command.replace('-', '_')}: {', '.join(unknown)}. "
                         f"Valid: {', '.join(actions)}")
    argv, stdin = [command], None
    positionals = []
    for prop, value in arguments.items():
        action = actions[prop]
        if value is None:
            continue
        if action.type is int and isinstance(value, float) and value.is_integer():
            value = int(value)
        values = value if isinstance(value, list) else [value]
        if not action.option_strings:
            positionals.append((action, [str(v) for v in values]))
            continue
        flag = max(action.option_strings, key=len)
        if isinstance(action, argparse._StoreTrueAction):
            if value:
                argv.append(flag)
        elif isinstance(action, argparse._AppendAction):
            argv += [f"{flag}={v}" for v in values]
        elif action.nargs in ("+", "*"):
            argv += [flag, *map(str, values)]
        else:
            argv.append(f"{flag}={value}")
    if command == "dax" and positionals:  # queries go through stdin: any length, quotes and newlines
        stdin = positionals[0][1][0]
        positionals = [(positionals[0][0], ["-"])]
    if positionals:
        order = [a for a in parser._actions if not a.option_strings]
        positionals.sort(key=lambda pv: order.index(pv[0]))
        argv.append("--")
        for _, vals in positionals:
            argv += vals
    return argv, stdin


# --------------------------------------------------------------------------- running tools

def _guide(topic: str | None) -> str:
    root = Path(__file__).with_name("skill") / "powerbi-builder"
    topic = topic or "workflow"
    if topic not in GUIDE_TOPICS:
        raise ValueError(f"Unknown topic {topic!r}. Topics: {', '.join(GUIDE_TOPICS)}")
    text = (root / GUIDE_TOPICS[topic]).read_text(encoding="utf-8")
    if text.startswith("---"):  # drop the skill's YAML front matter
        text = text.split("---", 2)[2].lstrip()
    return text


def _pngs(obj, found: list[str]) -> list[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file" and isinstance(v, str) and v.lower().endswith(".png"):
                found.append(v)
            else:
                _pngs(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _pngs(v, found)
    return found


def _image(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    data = p.read_bytes()
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) > MAX_IMAGE_SIDE or len(data) > MAX_IMAGE_BYTES:
                im = im.convert("RGB")
                im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
                buf = io.BytesIO()
                im.save(buf, "PNG", optimize=True)
                data = buf.getvalue()
    except Exception:  # noqa: BLE001  send the file as it is
        pass
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": "image/png"}


class Server:
    def __init__(self, images: bool = True, cwd: str | None = None):
        self.images = images
        self.cwd = cwd
        self._out_lock = threading.Lock()
        self._run_lock = threading.Lock()  # one tool at a time: they all drive the same Power BI window
        self._procs: dict = {}
        self._cancelled: set = set()

    # -- transport
    def send(self, msg: dict) -> None:
        line = json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._out_lock:
            sys.stdout.buffer.write(line.encode("utf-8"))
            sys.stdout.buffer.flush()

    def reply(self, rid, result=None, error=None) -> None:
        if rid in self._cancelled:
            self._cancelled.discard(rid)
            return
        self.send({"jsonrpc": "2.0", "id": rid, **({"error": error} if error else {"result": result})})

    # -- protocol
    def handle(self, msg: dict) -> None:
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method is None:
            return  # a response to something we never send
        if rid is None:  # notification
            if method == "notifications/cancelled":
                self.cancel(params.get("requestId"))
            return
        if method == "initialize":
            asked = params.get("protocolVersion")
            self.reply(rid, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False},
                                 "resources": {"listChanged": False}},
                "serverInfo": {"name": "pbidriver", "title": "pbidriver (Power BI Desktop driver)",
                               "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            self.reply(rid, {})
        elif method == "tools/list":
            self.reply(rid, {"tools": tool_list()})
        elif method == "tools/call":
            threading.Thread(target=self.call_tool, args=(rid, params), daemon=True).start()
        elif method == "prompts/list":
            self.reply(rid, {"prompts": PROMPTS})
        elif method == "prompts/get":
            self.get_prompt(rid, params)
        elif method == "resources/list":
            self.reply(rid, {"resources": [
                {"uri": f"pbidriver://guide/{t}", "name": f"guide-{t}", "title": f"pbidriver guide: {t}",
                 "mimeType": "text/markdown"} for t in GUIDE_TOPICS]})
        elif method == "resources/read":
            uri = params.get("uri", "")
            try:
                text = _guide(uri.rsplit("/", 1)[-1])
            except ValueError as e:
                self.reply(rid, error={"code": -32602, "message": str(e)})
                return
            self.reply(rid, {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]})
        elif method == "resources/templates/list":
            self.reply(rid, {"resourceTemplates": []})
        elif method == "logging/setLevel":
            self.reply(rid, {})
        else:
            self.reply(rid, error={"code": -32601, "message": f"Method not found: {method}"})

    def cancel(self, rid) -> None:
        self._cancelled.add(rid)
        proc = self._procs.get(rid)
        if proc and proc.poll() is None:
            proc.kill()

    def call_tool(self, rid, params: dict) -> None:
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        try:
            if name == PREFIX + "guide":
                self.reply(rid, {"content": [{"type": "text", "text": _guide(arguments.get("topic"))}]})
                return
            command = name[len(PREFIX):].replace("_", "-") if name.startswith(PREFIX) else ""
            if command not in _commands():
                self.reply(rid, error={"code": -32602, "message": f"Unknown tool: {name}"})
                return
            argv, stdin = build_argv(command, arguments)
        except ValueError as e:
            self.reply(rid, {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(e)})}],
                             "isError": True})
            return
        with self._run_lock:
            if rid in self._cancelled:
                self._cancelled.discard(rid)
                return
            result = self.run(rid, argv, stdin)
        text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
        content = [{"type": "text", "text": text}]
        if self.images and result.get("ok"):
            for path in _pngs(result, [])[:MAX_IMAGES]:
                img = _image(path)
                if img:
                    content.append(img)
        self.reply(rid, {"content": content, "isError": not result.get("ok", False)})

    def run(self, rid, argv: list[str], stdin: str | None) -> dict:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen([sys.executable, "-m", "pbidriver", *argv], cwd=self.cwd, env=env,
                                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        except OSError as e:
            return {"ok": False, "error": f"Could not start pbidriver: {e}"}
        self._procs[rid] = proc
        try:
            out, err = proc.communicate(stdin.encode("utf-8") if stdin is not None else None)
        finally:
            self._procs.pop(rid, None)
        text = out.decode("utf-8", "replace").strip()
        try:
            return json.loads(text)
        except ValueError:
            errtext = err.decode("utf-8", "replace").strip()
            if ": error: " in errtext:  # argparse usage error: its last line says what is wrong
                return {"ok": False, "error": errtext.rsplit(": error: ", 1)[1].strip()}
            tail = (errtext or text)[-1500:]
            return {"ok": False, "error": f"pbidriver {argv[0]} exited with code {proc.returncode}: {tail}"}

    def get_prompt(self, rid, params: dict) -> None:
        name, args = params.get("name"), params.get("arguments") or {}
        prompt = next((p for p in PROMPTS if p["name"] == name), None)
        if not prompt:
            self.reply(rid, error={"code": -32602, "message": f"Unknown prompt: {name}"})
            return
        text = PROMPT_TEXT[name].format(**{a["name"]: args.get(a["name"], "") or a.get("fallback", "")
                                           for a in prompt.get("arguments", [])})
        self.reply(rid, {"description": prompt["description"],
                         "messages": [{"role": "user", "content": {"type": "text", "text": text}}]})

    def serve(self) -> None:
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            for m in msg if isinstance(msg, list) else [msg]:
                try:
                    self.handle(m)
                except Exception as e:  # noqa: BLE001  never let one bad message stop the server
                    if isinstance(m, dict) and m.get("id") is not None:
                        self.reply(m["id"], error={"code": -32603, "message": f"{type(e).__name__}: {e}"})
        for proc in list(self._procs.values()):  # the client went away
            if proc.poll() is None:
                proc.kill()


PROMPTS = [
    {"name": "build-report", "title": "Build a Power BI report",
     "description": "Plan and build a report end to end: model with the Power BI Modeling MCP, pages and visuals "
                    "with pbidriver, verified with screenshots and DAX.",
     "arguments": [{"name": "goal", "description": "What the report should show", "required": True},
                   {"name": "data", "description": "Data source: CSV/Excel path, SQL server, or an existing .pbix/.pbip"},
                   {"name": "folder", "description": "Where to create the project"}]},
    {"name": "review-report", "title": "Review an open Power BI report",
     "description": "Look at every page of the open report, check visuals against the model, and list problems.",
     "arguments": []},
]

PROMPT_TEXT = {
    "build-report": "Build a Power BI report.\nGoal: {goal}\nData: {data}\nProject folder: {folder}\n\n"
                    "First call pbi_guide (topic workflow) and follow it: create or open the PBIP project with "
                    "pbidriver, build the semantic model with the Power BI Modeling MCP tools, refresh, add pages and "
                    "visuals with pbidriver, then verify every page with pbi_shot and pbi_read against pbi_dax. "
                    "Save at the end and show me the final screenshots.",
    "review-report": "Review the Power BI report that is open now. Use pbi_status, then for every page pbi_shot "
                     "annotate=true and pbi_read; spot-check numbers with pbi_dax; check pbi_alerts. Report broken "
                     "visuals, wrong or suspicious numbers, unreadable layouts, and missing titles, with page and "
                     "visual index for each.",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pbidriver mcp", description="Run pbidriver as an MCP server over stdio.")
    p.add_argument("--no-images", action="store_true", help="return screenshot paths only, not image content")
    p.add_argument("--cwd", help="working directory for commands (where relative paths and pbidriver_shots/ go)")
    a = p.parse_args(argv)
    Server(images=not a.no_images, cwd=a.cwd).serve()
    return 0
