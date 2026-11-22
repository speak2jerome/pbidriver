"""Power BI Desktop instances, Microsoft's Desktop Bridge, and DAX against the local model.

None of this needs DevTools, so it works with any running Power BI Desktop, including one
opened by double-clicking a file:

* instances()   every running Power BI Desktop: pid, window, file, DevTools port, Bridge, model port
* bridge_call() JSON-RPC 2.0 over the Desktop Bridge named pipe (Power BI Desktop June 2026+)
* run_dax()     DAX queries through the ADOMD.NET client that ships with Power BI Desktop
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PIPE_DIR = "\\\\.\\pipe\\"
PIPE_PREFIX = "pbi-desktop-bridge-"
BRIDGE_CLIENT = "pbidriver"


class BridgeError(Exception):
    """A Bridge or model call that failed; the message is meant for the user."""

    def __init__(self, message: str, reason: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable


# --------------------------------------------------------------------------- instances

def _bridge_pipes() -> set[int]:
    try:
        names = os.listdir(PIPE_DIR)
    except OSError:
        return set()
    return {int(n[len(PIPE_PREFIX):]) for n in names if n.startswith(PIPE_PREFIX) and n[len(PIPE_PREFIX):].isdigit()}


def _listen_ports(proc) -> list[int]:
    import psutil

    try:
        conns = proc.net_connections(kind="tcp")
    except (psutil.Error, AttributeError):
        try:
            conns = proc.connections(kind="tcp")  # psutil < 6
        except psutil.Error:
            return []
    return sorted({c.laddr.port for c in conns if c.status == psutil.CONN_LISTEN and c.laddr})


def main_window(pid: int):
    """(hwnd, title) of the largest visible, unowned, titled window of a process, or None."""
    import win32gui
    import win32process

    found = []

    def cb(hwnd, _):
        if (win32gui.IsWindowVisible(hwnd) and not win32gui.GetWindow(hwnd, 4)  # 4 = GW_OWNER
                and win32process.GetWindowThreadProcessId(hwnd)[1] == pid and win32gui.GetWindowText(hwnd)):
            left, top, right, bottom = win32gui.GetWindowPlacement(hwnd)[4]
            found.append(((right - left) * (bottom - top), hwnd))
        return True

    win32gui.EnumWindows(cb, None)
    if not found:
        return None
    hwnd = max(found)[1]
    return hwnd, win32gui.GetWindowText(hwnd)


def describe_instance(proc, pipes: set[int] | None = None) -> dict:
    """What is known about one PBIDesktop process, cheaply (no DevTools or Bridge calls)."""
    import psutil

    pipes = _bridge_pipes() if pipes is None else pipes
    info: dict = {"pid": proc.pid, "window_title": None, "file": None, "devtools_port": None,
                  "bridge": proc.pid in pipes, "model_port": None}
    win = main_window(proc.pid)
    if win:
        info["window_title"] = win[1]
    try:
        args = proc.cmdline()
        info["file"] = next((x for x in args[1:] if x.lower().endswith((".pbix", ".pbip", ".pbit"))), None)
        for child in proc.children(recursive=False):
            name = child.name().lower()
            if name == "msedgewebview2.exe" and info["devtools_port"] is None:
                m = re.search(r"--remote-debugging-port=(\d+)", " ".join(child.cmdline()))
                if m:
                    info["devtools_port"] = int(m.group(1))
            elif name == "msmdsrv.exe" and info["model_port"] is None:
                ports = _listen_ports(child)
                info["model_port"] = ports[0] if ports else None
    except psutil.Error:
        pass
    return info


def instances() -> list[dict]:
    import psutil

    pipes = _bridge_pipes()
    out = []
    for p in psutil.process_iter(["name"]):
        if (p.info.get("name") or "").lower() == "pbidesktop.exe":
            out.append(describe_instance(p, pipes))
    return sorted(out, key=lambda i: i["pid"])


def instance(pid: int) -> dict:
    import psutil

    try:
        return describe_instance(psutil.Process(pid))
    except psutil.Error:
        raise BridgeError(f"No Power BI Desktop process with pid {pid}.") from None


# --------------------------------------------------------------------------- Desktop Bridge

def bridge_call(pid: int, method: str, args: dict | None = None, timeout: float = 90, retries: int = 3) -> dict:
    """Call one Bridge method and return its `result`. The pipe serves one operation at a time,
    so a busy or retryable error is retried a few times."""
    for attempt in range(retries + 1):
        try:
            return _bridge_once(pid, method, args or {}, timeout)
        except BridgeError as e:
            if not e.retryable or attempt == retries:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def _bridge_once(pid: int, method: str, args: dict, timeout: float) -> dict:
    import pywintypes
    import win32file
    import win32pipe

    name = f"{PIPE_DIR}{PIPE_PREFIX}{pid}"
    try:
        win32pipe.WaitNamedPipe(name, 5000)
        handle = win32file.CreateFile(name, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                                      win32file.OPEN_EXISTING, 0, None)
    except pywintypes.error as e:
        if e.winerror == 231:  # ERROR_PIPE_BUSY
            raise BridgeError("The Desktop Bridge is busy with another client.", "Busy", True) from None
        raise BridgeError(
            f"No Desktop Bridge for Power BI process {pid}. It needs Power BI Desktop June 2026 or later, with "
            "Options > Security > 'Enable external tool access to Power BI Desktop through secure local APIs' on."
        ) from None

    request = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 1_000_000_000, "method": method,
               "params": {"client": BRIDGE_CLIENT, "args": args}}
    body = json.dumps(request).encode("utf-8")
    box: dict = {}

    def exchange():
        try:
            win32file.WriteFile(handle, b"Content-Length: %d\r\n\r\n" % len(body) + body)
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += win32file.ReadFile(handle, 65536)[1]
            head, rest = buf.split(b"\r\n\r\n", 1)
            length = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                          if line.lower().startswith(b"content-length"))
            while len(rest) < length:
                rest += win32file.ReadFile(handle, 1 << 20)[1]
            box["response"] = json.loads(rest[:length].decode("utf-8"))
        except Exception as e:  # noqa: BLE001  reported below
            box["error"] = e

    worker = threading.Thread(target=exchange, daemon=True)
    worker.start()
    worker.join(timeout)
    try:
        handle.Close()
    except Exception:  # noqa: BLE001
        pass
    if worker.is_alive():
        raise BridgeError(f"Desktop Bridge call {method} timed out after {timeout:.0f}s.", "Timeout")
    if "error" in box:
        raise BridgeError(f"Desktop Bridge call {method} failed: {box['error']}")
    response = box["response"]
    if "error" in response:
        err = response["error"]
        data = err.get("data") or {}
        raise BridgeError(err.get("message") or str(err), data.get("reason"), bool(data.get("retryable")))
    return response.get("result") or {}


def bridge_methods(pid: int) -> list[str]:
    return [m["name"] for m in bridge_call(pid, "bridge.manifest").get("methods", [])]


def bridge_state(pid: int) -> dict:
    r = bridge_call(pid, "application.state.get/v1", timeout=15)
    return {"file": r.get("currentFilePath") or None, "unsaved": bool(r.get("hasUnsavedChanges"))}


def bridge_snapshot(pid: int, page_id: str, scale: float = 1.0, region: dict | None = None) -> bytes:
    """PNG of a report page (or a region of it, in page units). Region needs capture/v2."""
    import base64

    args: dict = {"pageId": page_id, "scale": max(1.0, min(3.0, float(scale)))}
    method = "report.snapshot.capture/v1"
    if region is not None:
        args["region"] = {k: float(region[k]) for k in ("x", "y", "width", "height")}
        method = "report.snapshot.capture/v2"
    result = bridge_call(pid, method, args, timeout=60)
    if not result.get("payload"):
        raise BridgeError("The Desktop Bridge returned no image.")
    return base64.b64decode(result["payload"])


def bridge_reload(pid: int, model: bool = True) -> dict:
    return bridge_call(pid, "file.reload/v1", {"reloadModelDefinition": bool(model)}, timeout=300)


# --------------------------------------------------------------------------- DAX over ADOMD.NET

# Runs in Windows PowerShell 5.1 (.NET Framework), which can load the ADOMD.NET client that
# ships inside Power BI Desktop, so no extra Python or .NET packages are needed.
_ADOMD_PS = r"""
param([string]$Dll, [int]$Port, [string]$QueryFile, [int]$MaxRows, [int]$Timeout)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function Convert-Value($v) {
  if ($v -is [DBNull] -or $null -eq $v) { return $null }
  if ($v -is [DateTime]) { return $v.ToString('o') }
  if ($v -is [double] -and ([double]::IsNaN($v) -or [double]::IsInfinity($v))) { return [string]$v }
  return $v
}
$results = New-Object System.Collections.ArrayList
try {
  Add-Type -Path $Dll
  $cn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port")
  $cn.Open()
  $queries = [IO.File]::ReadAllText($QueryFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
  foreach ($q in $queries) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
      $cmd = $cn.CreateCommand(); $cmd.CommandText = $q; $cmd.CommandTimeout = $Timeout
      $r = $cmd.ExecuteReader()
      $cols = @(for ($i = 0; $i -lt $r.FieldCount; $i++) { $r.GetName($i) })
      $rows = New-Object System.Collections.ArrayList
      $total = 0
      while ($r.Read()) {
        $total++
        if ($rows.Count -lt $MaxRows) {
          $row = New-Object object[] $r.FieldCount
          for ($i = 0; $i -lt $r.FieldCount; $i++) { $row[$i] = Convert-Value $r.GetValue($i) }
          [void]$rows.Add($row)
        }
      }
      $r.Close()
      [void]$results.Add(@{ ok = $true; columns = $cols; rows = $rows; row_count = $total; ms = $sw.ElapsedMilliseconds })
    } catch {
      $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }
      [void]$results.Add(@{ ok = $false; error = $e.Message; ms = $sw.ElapsedMilliseconds })
    }
  }
  $cn.Close()
  ConvertTo-Json -InputObject @{ ok = $true; results = $results } -Depth 6 -Compress
} catch {
  ConvertTo-Json -InputObject @{ ok = $false; error = $_.Exception.Message } -Compress
}
"""


def adomd_dll(pid: int) -> Path:
    """The ADOMD.NET client bundled with this Power BI Desktop (env PBI_ADOMD_DLL overrides)."""
    import psutil

    override = os.environ.get("PBI_ADOMD_DLL")
    if override:
        return Path(override)
    try:
        bin_dir = Path(psutil.Process(pid).exe()).parent
    except psutil.Error:
        raise BridgeError(f"Cannot read the install folder of Power BI process {pid}.") from None
    for name in ("Microsoft.PowerBI.AdomdClient.dll", "Microsoft.AnalysisServices.AdomdClient.dll"):
        if (bin_dir / name).exists():
            return bin_dir / name
    raise BridgeError(f"No ADOMD.NET client found in {bin_dir}. Set PBI_ADOMD_DLL to Microsoft.AnalysisServices.AdomdClient.dll.")


def _clean_columns(cols: list[str]) -> list[str]:
    # ADOMD names columns like "[Name]" or "Table[Column]"; keep them readable but unambiguous.
    return [c[1:-1] if c.startswith("[") and c.endswith("]") and c.count("[") == 1 else c for c in cols]


def run_dax(pid: int, queries: list[str], max_rows: int = 1000, timeout: int = 120) -> list[dict]:
    """Run DAX queries against the model of one Power BI instance. One result per query:
    {"ok", "columns", "rows", "row_count", "truncated", "ms"} or {"ok": false, "error"}."""
    info = instance(pid)
    if not info["model_port"]:
        raise BridgeError("This Power BI instance has no running model engine (open a report with a data model).")
    dll = adomd_dll(pid)
    tmp = Path(tempfile.gettempdir())
    script = tmp / "pbidriver_adomd.ps1"
    if not script.exists() or script.read_text(encoding="utf-8") != _ADOMD_PS:
        script.write_text(_ADOMD_PS, encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(list(queries), f)
        query_file = f.name
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Dll", str(dll), "-Port", str(info["model_port"]), "-QueryFile", query_file,
             "-MaxRows", str(max_rows), "-Timeout", str(timeout)],
            capture_output=True, timeout=timeout + 60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise BridgeError("Windows PowerShell (powershell.exe) is needed to run DAX queries.") from None
    except subprocess.TimeoutExpired:
        raise BridgeError(f"DAX query timed out after {timeout}s.") from None
    finally:
        os.unlink(query_file)
    out = proc.stdout.decode("utf-8", "replace").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else None
    except (json.JSONDecodeError, IndexError):
        data = None
    if not data:
        raise BridgeError("DAX runner failed: " + (proc.stderr.decode("utf-8", "replace").strip()[:500] or out[:500]))
    if not data.get("ok"):
        raise BridgeError("Could not query the model: " + str(data.get("error")))
    results = data["results"]
    if isinstance(results, dict):  # a single result may come back unwrapped
        results = [results]
    for r in results:
        if r.get("ok"):
            r["columns"] = _clean_columns(r.get("columns") or [])
            rows = r.get("rows") or []
            if rows and not isinstance(rows[0], list):  # one-column rows may come back flattened
                rows = [[v] for v in rows]
            r["rows"] = rows
            r["truncated"] = r.get("row_count", 0) > len(rows)
    return results


_MODEL_QUERIES = {
    "tables": "EVALUATE INFO.VIEW.TABLES()",
    "columns": "EVALUATE INFO.VIEW.COLUMNS()",
    "measures": "EVALUATE INFO.VIEW.MEASURES()",
    "relationships": "EVALUATE INFO.VIEW.RELATIONSHIPS()",
}
_MODEL_DROP = {"ID", "Model", "LineageTag", "SourceLineageTag", "TableID", "ColumnID", "ModifiedTime",
               "StructureModifiedTime", "RefreshedTime", "State", "ErrorMessage", "IsPrivate",
               "ShowAsVariationOnly", "CalculationGroupPrecedence", "ExcludeFromModelRefresh",
               "LineageTagSourceTable", "SortByColumnID", "AttributeHierarchyID", "RelyOnReferentialIntegrity",
               "SecurityFilteringBehavior", "JoinOnDateBehavior", "IsUnique", "IsKey", "IsNullable",
               "IsAvailableInMDX", "KeepUniqueRows", "SummarizeBy", "Alignment", "TableDetailPosition",
               "IsDefaultLabel", "IsDefaultImage", "EncodingHint", "DisplayOrdinal", "SourceProviderType",
               "DetailRowsDefinition", "KPIID", "DataCategory", "FormatStringDefinition", "Annotations",
               "ColumnStorage", "TableStorage", "GroupingBehavior", "IsSimpleMeasure"}


def model_info(pid: int) -> dict:
    """Tables, columns, measures and relationships of the open model (INFO.VIEW DAX functions)."""
    names = list(_MODEL_QUERIES)
    results = run_dax(pid, [_MODEL_QUERIES[n] for n in names], max_rows=100_000)
    out: dict = {}
    for name, r in zip(names, results):
        if not r.get("ok"):
            out[name] = {"error": r.get("error")}
            continue
        keep = [i for i, c in enumerate(r["columns"]) if c not in _MODEL_DROP]
        rows = [{r["columns"][i]: row[i] for i in keep if row[i] not in (None, "")} for row in r["rows"]]
        out[name] = [x for x in rows if x.get("Type") != "RowNumber"]  # engine-internal columns
    return out
