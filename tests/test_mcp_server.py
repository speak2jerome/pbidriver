"""The MCP server: tool schemas generated from the CLI, argv building, and the stdio protocol. No Power BI needed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pbidriver import cli, mcp_server

ROOT = Path(__file__).resolve().parents[1]


def test_every_cli_command_is_a_tool():
    names = {t["name"] for t in mcp_server.tool_list()}
    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    for cmd in set(sub.choices) - mcp_server.NOT_TOOLS:
        assert "pbi_" + cmd.replace("-", "_") in names
    assert "pbi_guide" in names and "pbi_mcp" not in names and "pbi_setup" not in names


def test_schemas_are_well_formed():
    for tool in mcp_server.tool_list():
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and isinstance(schema["properties"], dict), tool["name"]
        assert set(schema.get("required", [])) <= set(schema["properties"]), tool["name"]
        assert len(tool["name"]) <= 64 and tool["description"], tool["name"]
        for prop in schema["properties"].values():
            assert prop["type"] in ("string", "integer", "number", "boolean", "array")
    tools = {t["name"]: t for t in mcp_server.tool_list()}
    av = tools["pbi_add_visual"]["inputSchema"]
    assert av["required"] == ["type"] and "clusteredColumnChart" in av["properties"]["type"]["enum"]
    assert av["properties"]["field"]["type"] == "array"
    assert tools["pbi_launch"]["inputSchema"]["required"] == ["file"]
    assert tools["pbi_key"]["inputSchema"]["properties"]["keys"]["type"] == "array"
    assert tools["pbi_shot"]["annotations"]["readOnlyHint"] and tools["pbi_close"]["annotations"]["destructiveHint"]
    assert "sync" in tools["pbi_refresh"]["inputSchema"]["properties"]
    shot = tools["pbi_shot"]["inputSchema"]["properties"]
    assert shot["overlay"]["type"] == "array" and "perf" in shot["overlay"]["items"]["enum"]
    assert shot["clean"]["type"] == "boolean" and shot["grid_size"]["type"] == "integer"
    perf = tools["pbi_perf"]["inputSchema"]["properties"]
    assert {"runs", "cold", "threshold", "top", "all_pages"} <= set(perf)
    assert {"runs", "cold"} <= set(tools["pbi_dax"]["inputSchema"]["properties"])
    assert "command" in tools["pbi_bug_report"]["inputSchema"]["properties"]  # --command maps to `command`
    assert tools["pbi_locate"]["annotations"]["readOnlyHint"]
    assert "clean" in tools["pbi_add_visual"]["inputSchema"]["properties"]
    assert "git" in tools["pbi_new"]["inputSchema"]["properties"]


@pytest.mark.parametrize("command,args,expect", [
    ("key", {"keys": ["Escape", "Control+A"]}, {"keys": ["Escape", "Control+A"]}),
    ("new", {"folder": "C:/x", "name": "Sales", "open": True}, {"folder": "C:/x", "name": "Sales", "open": True}),
    ("add-visual", {"type": "card", "field": ["[Total]", "Y=Sales[A]"], "x": 10, "title": "-dash"},
     {"type": "card", "field": ["[Total]", "Y=Sales[A]"], "x": 10.0, "title": "-dash"}),
    ("scroll", {"visual": "0", "dy": -300}, {"visual": "0", "dy": -300.0}),
    ("slicer", {"visual": "2", "select": ["A", "B"]}, {"visual": "2", "select": ["A", "B"]}),
    ("save", {"as": "C:/y.pbip", "overwrite": True}, {"as_path": "C:/y.pbip", "overwrite": True}),
    ("type", {"value": "-hello", "press": "Enter"}, {"value": "-hello", "press": "Enter"}),
    ("refresh", {"sync": True, "port": 9500}, {"sync": True, "port": 9500}),
    ("dax", {"max_rows": 5.0}, {"max_rows": 5}),
])
def test_argv_round_trips_through_the_cli_parser(command, args, expect):
    argv, stdin = mcp_server.build_argv(command, args)
    ns = vars(cli.build_parser().parse_args(argv))
    for k, v in expect.items():
        assert ns[k] == v, (k, ns[k])


def test_dax_queries_go_through_stdin():
    q = 'EVALUATE\n  ROW("x", "a ""quoted"" -value")'
    argv, stdin = mcp_server.build_argv("dax", {"query": q})
    assert stdin == q and argv[-1] == "-"


def test_unknown_argument_is_refused():
    with pytest.raises(ValueError, match="Valid:"):
        mcp_server.build_argv("shot", {"bogus": 1})


def test_png_paths_are_found_anywhere_in_a_result():
    result = {"file": "C:/report.pbip", "shot": {"file": "a.png"}, "visuals": [{"file": "b.PNG"}, {"x": 1}]}
    assert mcp_server._pngs(result, []) == ["a.png", "b.PNG"]


def test_guide_topics_exist(capsys):
    for topic in mcp_server.GUIDE_TOPICS:
        text = mcp_server._guide(topic)
        assert text.strip() and not text.startswith("---")
        assert cli.main(["guide", topic]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["text"] == text and Path(out["file"]).is_file()
    assert "pbi_refresh" in mcp_server._guide(None)
    # Every topic the guide names exists, and the skill links every reference file.
    skill = (Path(mcp_server.__file__).with_name("skill") / "powerbi-builder" / "SKILL.md").read_text(encoding="utf-8")
    for rel in mcp_server.GUIDE_TOPICS.values():
        if rel != "SKILL.md":
            assert f"]({rel})" in skill, rel


class Server:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-m", "pbidriver", "mcp"], cwd=ROOT, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.n = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        if notify:
            return None
        while True:
            reply = json.loads(self.p.stdout.readline())
            if reply.get("id") == self.n:
                return reply

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=20)


@pytest.fixture
def server():
    s = Server()
    yield s
    s.close()


def test_stdio_protocol(server):
    init = server.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "pytest", "version": "1"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["serverInfo"]["name"] == "pbidriver"
    assert "Modeling MCP" in init["instructions"] and "tools" in init["capabilities"]
    server.send("notifications/initialized", notify=True)
    assert server.send("ping")["result"] == {}
    tools = server.send("tools/list")["result"]["tools"]
    assert len(tools) > 30
    guide = server.send("tools/call", {"name": "pbi_guide", "arguments": {"topic": "visuals"}})["result"]
    assert not guide.get("isError") and "pivotTable" in guide["content"][0]["text"]
    bad = server.send("tools/call", {"name": "pbi_add_visual", "arguments": {"type": "nope"}})["result"]
    assert bad["isError"] and "invalid choice" in json.loads(bad["content"][0]["text"])["error"]
    bad = server.send("tools/call", {"name": "pbi_shot", "arguments": {"bogus": True}})["result"]
    assert bad["isError"] and "Unknown argument" in bad["content"][0]["text"]
    assert server.send("tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32602
    res = server.send("resources/list")["result"]["resources"]
    text = server.send("resources/read", {"uri": res[0]["uri"]})["result"]["contents"][0]["text"]
    assert "pbi_new" in text
    prompt = server.send("prompts/get", {"name": "build-report", "arguments": {"goal": "sales by region"}})["result"]
    assert "sales by region" in prompt["messages"][0]["content"]["text"]
    assert server.send("bogus/method")["error"]["code"] == -32601


def test_unknown_protocol_version_gets_the_latest(server):
    init = server.send("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}})["result"]
    assert init["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]
