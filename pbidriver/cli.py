#!/usr/bin/env python3
r"""pbidriver: WebDriver for Power BI Desktop. Build, see and drive reports from AI agents.

Power BI Desktop draws its UI in WebView2 (Chromium) pages, one per view. Started with a
DevTools port, those pages can be captured pixel-for-pixel and driven with real input:
report canvas and single visuals, the Table/Model/DAX/TMDL views, slicers, scrolling.
Blocking dialogs (WebView2, native and legacy IE ones) are detected, read and answered.
PBIP projects can be created and given pages and visuals; the model is built with Microsoft's
Power BI Modeling MCP. `pbidriver mcp` serves every command as an MCP tool.

Instances without DevTools still get page/visual captures, reloads and state through Microsoft's
Desktop Bridge (Power BI Desktop June 2026+), and DAX queries through the bundled ADOMD.NET client.

pbidriver is a new tool: work on a copy of a report, or keep it in git and commit before changing it.
Found a bug? `pbidriver bug-report` drafts an issue for https://github.com/speak2jerome/pbidriver.

Every command prints one JSON object: {"ok": true, ...} or {"ok": false, "error": ...}.
Commands that touch the UI also return "alerts" (dialogs, banners, broken visuals) when any exist.

  launch "C:\path\report.pbix"          isolated instance with DevTools on --port
  instances | status | pages | alerts
  visuals [--page P] [--all-pages]      live visual list: type, label, box, text, error
  inventory [--file F]                  pages, visuals, fields, filters, bookmarks from the report file
  shot [--page P] [--visual V | --all-visuals | --full] [--view table|model|dax|tmdl] [--bridge]
       [--clean | --annotate | --overlay index type title size pos errors perf grid align gaps overlap all]
  read [--visual V]                     data behind visuals: chart points, cards, tables/matrices, slicers
  dax "EVALUATE ..." [--runs N --cold] | model     query (and time) the model / list its tables, measures...
  perf [--page P | --all-pages] [--runs N] [--cold] [--queries]   Performance Analyzer, bottlenecks, hints
  new | layout | add-page | add-visual | remove-visual | save --as | refresh --sync   build PBIP reports
  mcp | setup | doctor | locate | guide | bug-report                                 agents and the kit
  dialog [--click BUTTON | --shot]      read / answer / capture the blocking dialog
  click  [--visual V] [--text T | --at X,Y] [--ctrl] [--double] [--right] [--shot]
  hover  [--visual V] [--text T | --at X,Y] [--shot]       read the tooltip
  menu   [--visual V] [--text T | --at X,Y | --more] [--choose "A > B"]   context / More-options menus
  scroll [--visual V | --text T | --at X,Y] --dx N --dy N [--shot]
  type TEXT [--visual V] [--into T] [--press KEY] [--shot]
  key KEY [KEY ...] [--shot]
  slicer --visual V [--select A B ... | --clear] [--shot]
  bookmarks [--apply NAME] [--shot]
  wait --text T [--gone]                wait for text to appear / disappear
  reload | save | close [--discard | --save]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pbidriver import __version__, bridge
from pbidriver.definition import report_inventory

DEFAULT_PORT = int(os.environ.get("PBIDRIVER_PORT", "9333"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
PROFILE_ROOT = LOCALAPPDATA / "pbidriver"

VIEWS = {
    "report": "reportView.html",
    "table": "dataExploreView.html",
    "model": "modelView.html",
    "dax": "daxQueryView.html",
    "tmdl": "tmdlView.html",
}
DIALOG_HOST = "desktopDialogHost.html"
CANVAS = "div.displayArea"
PAGE_TAB = "div.section.thumbnail-container"
MODIFIER = {"ctrl": "Control", "shift": "Shift", "alt": "Alt"}

# Local DevTools calls must never go through a configured HTTP proxy.
_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DriverError(Exception):
    """Expected failure, reported as {"ok": false, "error": ...}."""


# --------------------------------------------------------------------------- page-side JavaScript

# Resolves once the report canvas has had no DOM mutations for quietMs (or timeoutMs passes).
# On pages without a canvas it watches the whole document.
SETTLE_JS = r"""
async ([quietMs, timeoutMs]) => {
  const start = performance.now();
  let last = start;
  const hasCanvas = !!document.querySelector('div.displayArea');
  const relevant = (n) => {
    if (!hasCanvas) return true;
    const el = n && (n.nodeType === 1 ? n : n.parentElement);
    return !!(el && el.closest && el.closest('explore-canvas, div.exploration, div.displayArea'));
  };
  const obs = new MutationObserver((records) => {
    if (records.some(r => relevant(r.target))) last = performance.now();
  });
  obs.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  return await new Promise(resolve => {
    const tick = () => {
      const now = performance.now();
      if (now - last >= quietMs) { obs.disconnect(); resolve({ settled: true, ms: Math.round(now - start) }); }
      else if (now - start >= timeoutMs) { obs.disconnect(); resolve({ settled: false, ms: Math.round(now - start) }); }
      else setTimeout(tick, 50);
    };
    tick();
  });
}
"""

PAGES_JS = r"""
() => [...document.querySelectorAll('div.section.thumbnail-container')].map((t, i) => ({
  index: i,
  name: (t.innerText || t.getAttribute('aria-label') || '').split('\n')[0].trim(),
  selected: t.classList.contains('selected'),
  hidden: t.classList.contains('hidden-tab'),
}))
"""

CANVAS_JS = r"""
() => {
  const r = document.querySelector('div.displayArea')?.getBoundingClientRect();
  return r ? { w: Math.round(r.width), h: Math.round(r.height) } : null;
}
"""

# Geometry (viewport CSS px) of a capture target ('canvas' or visual #index), of the report
# canvas, and of the visible client area of the scroll container that clips the canvas.
GEOM_JS = r"""
([kind, index]) => {
  const area = document.querySelector('div.displayArea');
  if (!area) return null;
  const c = area.closest('div.displayAreaContainer') || area.parentElement;
  const target = kind === 'canvas' ? area
    : area.querySelectorAll('visual-container')[index]?.querySelector('div.visualContainer');
  if (!target) return null;
  const box = (r) => ({ x: r.left, y: r.top, w: r.width, h: r.height });
  const cr = c.getBoundingClientRect(), ar = area.getBoundingClientRect();
  return {
    viewport: { w: innerWidth, h: innerHeight },
    client: { x: cr.left + c.clientLeft, y: cr.top + c.clientTop, w: c.clientWidth, h: c.clientHeight },
    area: box(ar),
    target: box(target.getBoundingClientRect()),
    zoom: ar.width ? area.offsetWidth / ar.width : 1,
  };
}
"""

VISUALS_JS = r"""
(textLimit) => {
  const area = document.querySelector('div.displayArea');
  if (!area) return null;
  const a = area.getBoundingClientRect();
  const GENERIC = new Set(['', 'Image', 'Card', 'Navigating to visual', 'Can be sorted']);
  const ERR = /can['’]t display this visual|couldn['’]t load the data|couldn['’]t retrieve the data|something['’]s wrong with one or more fields|this visual has exceeded the available resources|see details/i;
  const clean = (s) => (s || '').replace(/Scroll (up|down|left|right)/g, ' ').replace(/\s+/g, ' ').trim();
  const visuals = [...area.querySelectorAll('visual-container')].map((v, index) => {
    const box = v.querySelector('div.visualContainer') || v;
    const r = box.getBoundingClientRect();
    const vis = v.querySelector('div.visual');
    let type = vis ? ([...vis.classList].find(c => c.startsWith('visual-') && c !== 'visual-sandbox') || '').replace(/^visual-/, '') : '';
    const guid = type.match(/^(.*?)([0-9A-F]{32})$/i);
    if (guid) type = guid[1];
    const title = clean(v.querySelector('.visualTitle')?.innerText);
    const aria = [...v.querySelectorAll('[aria-label]')].map(e => clean(e.getAttribute('aria-label')))
      .find(s => !GENERIC.has(s) && !/^[\d.,%\s-]+$/.test(s)) || '';  // skip axis ticks like "0%"
    const text = clean(v.innerText);
    const err = text.match(ERR);
    return {
      index,
      type: type || 'unknown',
      custom: !!guid || !!v.querySelector('iframe.visual-sandbox'),
      label: title || aria || text.slice(0, 60),
      title,
      box: { x: Math.round((r.x - a.x) * 10) / 10, y: Math.round((r.y - a.y) * 10) / 10,
             w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 },
      hidden: r.width < 1 || r.height < 1,
      error_text: err ? err[0] : null,
      text: textLimit > 0 ? text.slice(0, textLimit) : text,
    };
  });
  return { canvas: { w: Math.round(a.width), h: Math.round(a.height) }, visuals };
}
"""

# In-app (WebView2) dialogs and message banners on one page.
WEB_ALERTS_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width < 3 || r.height < 3) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.01; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const outer = (els) => els.filter(e => !els.some(o => o !== e && o.contains(e)));
  const notTip = (e) => !e.closest('.tooltip-container, visual-tooltip-modern, [role=tooltip]');
  const dialogs = outer([...document.querySelectorAll('mat-dialog-container, [role=dialog], [role=alertdialog], [aria-modal=true]')].filter(e => vis(e) && notTip(e)))
    .map(d => ({ text: clean(d.innerText).slice(0, 500),
      buttons: [...d.querySelectorAll('button, [role=button]')].filter(vis).map(b => clean(b.innerText) || clean(b.getAttribute('aria-label'))).filter(Boolean) }));
  const banners = [...new Set(outer([...document.querySelectorAll('div.message-banner, [role=alert]')].filter(vis))
    .filter(b => !b.closest('div.displayArea')).map(b => clean(b.innerText)).filter(Boolean))];
  return { dialogs, banners };
}
"""

# A legacy floating dialog page (e.g. FloatingDialog/KoBrowserDialog.htm: the Refresh progress/error
# dialog): the whole page is the dialog.
FLOATING_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const text = clean(document.body ? document.body.innerText : '').slice(0, 800);
  const buttons = [...document.querySelectorAll('button, [role=button], input[type=button], input[type=submit], a.button')]
    .filter(vis).map(b => clean(b.innerText || b.value || b.getAttribute('aria-label'))).filter(Boolean);
  return { text, buttons: [...new Set(buttons)] };
}
"""

# Candidate elements to act on, matched by aria-label or own text. scope: 'page' | 'visual' | 'dialog'.
FIND_JS = r"""
([scope, index, text, exact]) => {
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = (s) => (s || '').replace(/[‘’]/g, "'").replace(/\s+/g, ' ').trim();
  text = clean(text);
  let root = document.body;
  if (scope === 'visual') root = document.querySelector('div.displayArea')?.querySelectorAll('visual-container')[index];
  if (scope === 'dialog') root = [...document.querySelectorAll('mat-dialog-container, [role=dialog], [role=alertdialog], [aria-modal=true]')].filter(vis).pop();
  if (!root) return null;
  const t = text.toLowerCase();
  const out = [];
  for (const e of root.querySelectorAll('*')) {
    if (!vis(e)) continue;
    const label = clean(e.getAttribute('aria-label'));
    const own = clean([...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' '));
    let score = null;
    for (const s of [label, own]) {
      if (!s) continue;
      const l = s.toLowerCase();
      if (l === t) score = 0; else if (!exact && l.includes(t) && score === null) score = 1;
    }
    if (score === null) continue;
    const r = e.getBoundingClientRect();
    out.push({ score, area: r.width * r.height, x: r.left + r.width / 2, y: r.top + r.height / 2,
               tag: e.tagName.toLowerCase(), role: e.getAttribute('role'), label: label || own });
  }
  out.sort((a, b) => a.score - b.score || a.area - b.area);
  return out.slice(0, 5);
}
"""

# A point to aim the mouse at: centre of the *visible* part of a visual / the canvas / a grid.
ANCHOR_JS = r"""
([kind, index]) => {
  const clip = (r, c) => {
    const x0 = Math.max(r.left, c.left, 0), y0 = Math.max(r.top, c.top, 0);
    const x1 = Math.min(r.right, c.right, innerWidth), y1 = Math.min(r.bottom, c.bottom, innerHeight);
    return x1 > x0 && y1 > y0 ? { x: (x0 + x1) / 2, y: (y0 + y1) / 2 } : null;
  };
  const view = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
  const area = document.querySelector('div.displayArea');
  const cont = area ? (area.closest('div.displayAreaContainer') || area.parentElement).getBoundingClientRect() : view;
  if (kind === 'visual') {
    const v = area?.querySelectorAll('visual-container')[index]?.querySelector('div.visualContainer');
    return v ? clip(v.getBoundingClientRect(), cont) : null;
  }
  if (area) return clip(area.getBoundingClientRect(), cont);
  const grid = [...document.querySelectorAll('[role=grid], [role=treegrid]')].find(g => g.getBoundingClientRect().width > 2);
  return grid ? clip(grid.getBoundingClientRect(), view) : { x: innerWidth / 2, y: innerHeight / 2 };
}
"""

# Slicer state: dropdown header + the options currently rendered (in the popup when open).
SLICER_JS = r"""
(index) => {
  const v = document.querySelector('div.displayArea')?.querySelectorAll('visual-container')[index];
  if (!v) return null;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const combo = v.querySelector('[role=combobox]');
  let scope = v;
  const expanded = combo ? combo.getAttribute('aria-expanded') === 'true' : null;
  if (combo && expanded) scope = document.getElementById(combo.getAttribute('aria-controls')) || v;
  const items = [...scope.querySelectorAll('[role=option], [role=checkbox], [role=radio], [role=treeitem]')].filter(vis).map(i => {
    const r = i.getBoundingClientRect();
    return { label: clean(i.getAttribute('aria-label') || i.innerText),
             selected: (i.getAttribute('aria-selected') || i.getAttribute('aria-checked')) === 'true',
             x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  const cr = combo?.getBoundingClientRect();
  return { dropdown: !!combo, expanded, header: combo ? clean(combo.innerText) : null,
           combo: cr ? { x: cr.left + cr.width / 2, y: cr.top + cr.height / 2 } : null, items };
}
"""

# Data behind a visual. Built-in visuals bind each data point (d3 __data__) with tooltipInfo:
# [{displayName, value}], formatted exactly as Power BI shows it; cards bind {displayName, value}.
READ_JS = r"""
(index) => {
  const v = document.querySelector('div.displayArea')?.querySelectorAll('visual-container')[index];
  if (!v) return null;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const points = [], seen = new Set(), cards = [];
  const take = (d) => {
    if (!d || typeof d !== 'object' || !Array.isArray(d.tooltipInfo) || !d.tooltipInfo.length) return false;
    const pairs = d.tooltipInfo.map(t => [clean(String(t.displayName ?? '')), clean(String(t.value ?? ''))]);
    const key = String(d.key || d.identity?._key || '') + JSON.stringify(pairs);
    if (!seen.has(key)) { seen.add(key); points.push(pairs); }
    return true;
  };
  for (const el of v.querySelectorAll('*')) {
    const d = el.__data__;
    if (!d || typeof d !== 'object') continue;
    if (take(d)) continue;
    if (!Array.isArray(d) && typeof d.displayName === 'string' && 'value' in d && typeof d.value !== 'object') {
      const c = [clean(d.displayName), clean(String(d.value))];
      if (!cards.some(x => x[0] === c[0] && x[1] === c[1])) cards.push(c);
      continue;
    }
    for (const k of ['data', 'dataPoints', 'values', 'points']) {
      if (Array.isArray(d[k])) d[k].forEach(take);
      else if (d[k] && typeof d[k] === 'object') take(d[k]);  // pie/donut slices wrap the point: d.data
    }
    if (Array.isArray(d)) d.forEach(take);
  }
  return { points, cards, grid: !!v.querySelector('[role=grid], [role=treegrid]'), iframe: !!v.querySelector('iframe'),
           text: clean((v.innerText || '').replace(/Scroll (up|down|left|right)/g, ' ')).slice(0, 2000) };
}
"""

# Rendered cells of a table/matrix (virtualized: only what is on screen) with their aria indices.
GRID_JS = r"""
(index) => {
  const v = document.querySelector('div.displayArea')?.querySelectorAll('visual-container')[index];
  const g = v && v.querySelector('[role=grid], [role=treegrid]');
  if (!g) return null;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const cells = [];
  [...g.querySelectorAll('[role=row]')].forEach((row, i) => {
    const r = +row.getAttribute('aria-rowindex') || -(i + 1);
    [...row.querySelectorAll('[role=gridcell], [role=columnheader], [role=rowheader]')].forEach((c, j) =>
      cells.push([r, +c.getAttribute('aria-colindex') || (j + 1), clean(c.innerText), c.getAttribute('role')[0]]));
  });
  const gr = g.getBoundingClientRect();
  return { rowcount: +g.getAttribute('aria-rowcount') || null, colcount: +g.getAttribute('aria-colcount') || null,
           cells, anchor: { x: gr.left + gr.width / 2, y: gr.top + gr.height / 2 }, height: gr.height };
}
"""

TOOLTIP_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width < 3 || r.height < 3) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.01; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const tips = [...document.querySelectorAll('div.tooltip-container')].filter(vis);
  if (!tips.length) return null;
  const t = tips[tips.length - 1];
  const rows = [...t.querySelectorAll('.tooltip-row')].map(r => [clean(r.querySelector('.tooltip-title-cell')?.innerText),
                                                               clean(r.querySelector('.tooltip-value-cell')?.innerText)]);
  return { rows, text: clean(t.innerText).slice(0, 1500) };
}
"""

# Open menus (context menu, More options, submenus), outermost first, with clickable items.
MENU_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width < 3 || r.height < 3) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('[role=menu]')].filter(vis).map(m =>
    [...m.querySelectorAll('[role=menuitem], [role=menuitemcheckbox], [role=menuitemradio]')]
      .filter(i => vis(i) && i.closest('[role=menu]') === m)
      .map(i => { const r = i.getBoundingClientRect();
        return { label: clean(i.getAttribute('aria-label') || i.innerText), disabled: i.getAttribute('aria-disabled') === 'true',
                 submenu: !!i.getAttribute('aria-haspopup') && i.getAttribute('aria-haspopup') !== 'false',
                 checked: i.getAttribute('aria-checked'), x: r.left + r.width / 2, y: r.top + r.height / 2 }; }))
    .filter(items => items.length);
}
"""

# Ribbon tabs (File/Home/.../View/Optimize) and the pane toggle buttons on them.
RIBBON_JS = r"""
(label) => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const center = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  const lists = [...document.querySelectorAll('[role=tablist]')].filter(l =>
    [...l.querySelectorAll('[role=tab]')].some(t => clean(t.innerText) === 'Home'));
  const tabs = lists.length ? [...lists[0].querySelectorAll('[role=tab]')].filter(vis).map(t =>
    ({ name: clean(t.innerText || t.getAttribute('aria-label')), selected: t.getAttribute('aria-selected') === 'true', ...center(t) })) : [];
  const b = label ? [...document.querySelectorAll('button[aria-label][aria-pressed]')]
    .find(b => b.getAttribute('aria-label') === label && vis(b)) : null;
  return { tabs, toggle: b ? { pressed: b.getAttribute('aria-pressed') === 'true', ...center(b) } : null };
}
"""

BOOKMARKS_JS = r"""
() => {
  const pane = document.querySelector('pbi-pane.bookmarks-pane');
  if (!pane) return null;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  return [...pane.querySelectorAll('[role=treeitem].bookmark')].map(b => { const r = b.getBoundingClientRect();
    return { label: clean(b.getAttribute('aria-label') || b.innerText), x: r.left + r.width / 2, y: r.top + r.height / 2,
             visible: r.width > 2 && r.height > 2 }; });
}
"""

PERF_PANE = "pbi-pane.performancePaneContainer"
PERF_JS = r"""
() => {
  const pane = document.querySelector('pbi-pane.performancePaneContainer');
  if (!pane) return null;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  let copyIndex = 0;
  for (const tr of pane.querySelectorAll('tr')) {
    const cells = [...tr.querySelectorAll('td')].map(td => clean(td.innerText));
    if (tr.classList.contains('visualLifecycle')) {
      out.push({ name: cells[0], total_ms: cells[1] === '' ? null : +cells[1], expanded: tr.classList.contains('itemExpanded'), copy: null });
    } else if (out.length && cells.length) {
      const last = out[out.length - 1];
      const key = { 'DAX query': 'dax_query_ms', 'Visual display': 'visual_display_ms', 'Other': 'other_ms',
                    'Direct query': 'direct_query_ms', 'Evaluated parameters': 'parameters_ms' }[cells[0]];
      if (key) last[key] = cells[1] === '' ? null : +cells[1];
      if (cells[0] === 'Copy query') last.copy = copyIndex++;
    }
  }
  return out;
}
"""


# --------------------------------------------------------------------------- DevTools + process helpers

def _http_json(port: int, path: str):
    try:
        with _HTTP.open(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def _wait_for(pred, timeout: float, message: str, interval: float = 0.5):
    deadline = time.time() + timeout
    while True:
        value = pred()
        if value:
            return value
        if time.time() > deadline:
            raise DriverError(message)
        time.sleep(interval)


def _has_target(port: int, url_part: str) -> bool:
    return any(url_part in t.get("url", "") for t in (_http_json(port, "/json/list") or []))


def find_pbi_exe() -> Path:
    override = os.environ.get("PBI_DESKTOP_EXE")
    candidates = [Path(override)] if override else []
    candidates += [
        LOCALAPPDATA / "Microsoft" / "WindowsApps" / "PBIDesktopStore.exe",  # Microsoft Store build
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Power BI Desktop" / "bin" / "PBIDesktop.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise DriverError("Power BI Desktop not found. Set PBI_DESKTOP_EXE to the full path of PBIDesktop.exe.")


def pbi_window(port: int):
    """(hwnd, title, pid) of the main Power BI window whose WebView2 listens on `port`, or None."""
    import psutil

    try:
        browser_pid = next(
            c.pid for c in psutil.net_connections(kind="tcp")
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port
        )
        pbi_pid = psutil.Process(browser_pid).ppid()
    except (StopIteration, psutil.Error):
        return None
    win = bridge.main_window(pbi_pid)
    return (win[0], win[1], pbi_pid) if win else None


def resolve_pid(a) -> int:
    """The Power BI process to act on: --pid, else the DevTools instance on --port, else the only one running."""
    if getattr(a, "pid", None):
        return a.pid
    if _http_json(a.port, "/json/version"):
        win = pbi_window(a.port)
        if win:
            return win[2]
    found = bridge.instances()
    if len(found) == 1:
        return found[0]["pid"]
    if not found:
        raise DriverError("Power BI Desktop is not running.")
    raise DriverError("Several Power BI windows are open; pass --pid. "
                    + "; ".join(f"{i['pid']}: {i['window_title']}" for i in found))


def report_file(port: int) -> str | None:
    """The report path Power BI was started with (from its command line), if any."""
    import psutil

    win = pbi_window(port)
    if not win:
        return None
    try:
        args = psutil.Process(win[2]).cmdline()
    except psutil.Error:
        return None
    return next((x for x in args[1:] if x.lower().endswith((".pbix", ".pbip", ".pbit"))), None)


@contextmanager
def visible_window(port: int | None = None, pid: int | None = None):
    """WebView2 (and so the Desktop Bridge) stops painting while minimized, so restore the
    window without focusing it for the duration, then put it back exactly as it was."""
    import win32con
    import win32gui

    win = bridge.main_window(pid) if pid else (pbi_window(port) if port is not None else None)
    hwnd = win[0] if win else None
    restored = bool(hwnd and win32gui.IsIconic(hwnd))
    placement = win32gui.GetWindowPlacement(hwnd) if restored else None
    if restored:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        time.sleep(0.5)
    try:
        yield restored
    finally:
        if restored and win32gui.IsWindow(hwnd):
            # Put back the exact placement (incl. "restore to maximized"), minimized and unfocused.
            flags, _, pt_min, pt_max, rc_normal = placement
            win32gui.SetWindowPlacement(hwnd, (flags, win32con.SW_SHOWMINNOACTIVE, pt_min, pt_max, rc_normal))


class Session:
    """The Power BI WebView2 pages of one instance, keyed by view name."""

    def __init__(self, port: int, pages: dict, browser=None):
        self.port = port
        self.pages = pages
        self.browser = browser
        self._cdp: dict[int, object] = {}

    def floating_pages(self) -> dict:
        """Legacy floating dialog pages (any page that isn't a view or the dialog host) that are on screen.
        Power BI hides a closed floating dialog instead of destroying it, so its page (and its old text)
        lingers; only count them while a WebView2-hosting dialog window is visible."""
        if not any(w["kind"] == "webview2" for w in native_windows(self.port)["windows"]):
            return {}
        self.refresh_pages()
        known = set(VIEWS.values()) | {DIALOG_HOST}
        return {k: p for k, p in self.pages.items() if k not in known and not p.is_closed()}

    def refresh_pages(self) -> None:
        """Pick up pages created since connecting (e.g. the dialog host page of a new error dialog)."""
        if self.browser is None:
            return
        for ctx in self.browser.contexts:
            for pg in ctx.pages:
                key = pg.url.split("?")[0].rsplit("/", 1)[-1]
                if key not in self.pages or self.pages[key].is_closed():
                    self.pages[key] = pg

    def view(self, name: str):
        page = self.pages.get(VIEWS.get(name, name))
        if page is None:
            raise DriverError(f"The '{name}' view is not available in this Power BI instance.")
        return page

    @property
    def report(self):
        return self.view("report")

    def cdp(self, page):
        if id(page) not in self._cdp:
            self._cdp[id(page)] = page.context.new_cdp_session(page)
        return self._cdp[id(page)]


@contextmanager
def pbi_session(port: int, wait: float = 15):
    if not _http_json(port, "/json/version"):
        raise DriverError(
            f"No Power BI DevTools endpoint on 127.0.0.1:{port}. This command needs an instance started with "
            "`pbidriver launch <file.pbix|file.pbip>`. (Any open Power BI still supports status, shot, dialog, "
            "inventory, dax, model, reload and close.)"
        )
    _wait_for(lambda: _has_target(port, VIEWS["report"]), wait, "Power BI is running but its report view has not loaded yet.")
    os.environ.setdefault("NODE_NO_WARNINGS", "1")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        pages = {}
        for ctx in browser.contexts:
            for pg in ctx.pages:
                pages.setdefault(pg.url.split("?")[0].rsplit("/", 1)[-1], pg)
        if VIEWS["report"] not in pages:
            raise DriverError("Connected, but no report view page was found.")
        yield Session(port, pages, browser)


def settle(page, timeout_s: float, quiet_ms: int = 700) -> dict:
    return page.evaluate(SETTLE_JS, [quiet_ms, int(timeout_s * 1000)])


def _grab(cdp, x: float, y: float, w: float, h: float, scale: float) -> bytes:
    """Page.captureScreenshot of a viewport rect; clip.scale re-rasterizes (sharp, not upscaled)."""
    clip = {"x": x, "y": y, "width": w, "height": h, "scale": scale}
    return base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "png", "clip": clip})["data"])


def _fits(g: dict) -> bool:
    t, c = g["target"], g["client"]
    return (t["w"] >= 1 and t["h"] >= 1 and t["x"] >= c["x"] - 0.5 and t["y"] >= c["y"] - 0.5
            and t["x"] + t["w"] <= c["x"] + c["w"] + 0.5 and t["y"] + t["h"] <= c["y"] + c["h"] + 0.5)


@contextmanager
def fit_canvas(page, cdp, settle_s: float):
    """If the report canvas doesn't fit the visible area (small window, zoomed in), emulate a
    larger viewport until exit. Power BI resets script-driven scrolling, so this is the reliable way
    to have every visual on screen for capture or input."""
    g = page.evaluate(GEOM_JS, ["canvas", 0])
    override = None
    if g and not _fits(g):
        pad = 32
        w = int(g["viewport"]["w"] + max(0, g["area"]["w"] - g["client"]["w"]) + pad)
        h = int(g["viewport"]["h"] + max(0, g["area"]["h"] - g["client"]["h"]) + pad)
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 0, "mobile": False})
        override = [w, h]
        settle(page, settle_s, quiet_ms=500)
    try:
        yield override
    finally:
        if override:
            cdp.send("Emulation.clearDeviceMetricsOverride")
            settle(page, settle_s, quiet_ms=300)


def capture_target(page, cdp, kind: str, index: int, scale: float, path: Path) -> dict:
    """Capture the canvas or one visual (call inside fit_canvas). Only the target's own rectangle
    is captured, so ribbon, panes and scrollbars never leak in."""
    g = page.evaluate(GEOM_JS, [kind, index])
    if not g or not _fits(g):
        raise DriverError("Capture target is not fully visible (hidden, zero size, or outside the canvas).")
    zoom = g["zoom"] if 0.25 <= g["zoom"] <= 4 else 1.0
    t = g["target"]
    path.write_bytes(_grab(cdp, t["x"], t["y"], t["w"], t["h"], scale * zoom))  # native page resolution x --scale
    return {"zoom": round(zoom, 3)}


def capture_page(page, cdp, scale: float, path: Path) -> None:
    w, h = page.evaluate("[innerWidth, innerHeight]")
    path.write_bytes(_grab(cdp, 0, 0, w, h, scale))


# --------------------------------------------------------------------------- native / legacy dialogs

def _children(hwnd) -> list[int]:
    import win32gui

    kids: list[int] = []
    win32gui.EnumChildWindows(hwnd, lambda c, _: kids.append(c) or True, None)
    return kids


def _mshtml_document(ie_hwnd):
    """IHTMLDocument of a legacy Internet Explorer_Server control, via WM_HTML_GETOBJECT."""
    import pythoncom
    import win32com.client
    import win32con
    import win32gui

    pythoncom.CoInitialize()
    msg = win32gui.RegisterWindowMessage("WM_HTML_GETOBJECT")
    _, lres = win32gui.SendMessageTimeout(ie_hwnd, msg, 0, 0, win32con.SMTO_ABORTIFHUNG, 3000)
    if not lres:
        return None
    return win32com.client.dynamic.Dispatch(pythoncom.ObjectFromLresult(lres, pythoncom.IID_IDispatch, 0))


def _mshtml_buttons(doc) -> list[tuple[str, object]]:
    doc._FlagAsMethod("querySelectorAll")
    els = doc.querySelectorAll("button, [role=button], input[type=button], input[type=submit]")
    els._FlagAsMethod("item")
    out = []
    for i in range(els.length):
        e = els.item(i)
        e._FlagAsMethod("getAttribute", "click")
        label = (e.innerText or e.getAttribute("aria-label") or e.getAttribute("value") or "").strip()
        if label and e.offsetWidth > 0:
            out.append((label, e))
    return out


def _native_buttons(hwnd) -> list[tuple[str, int]]:
    import win32gui

    return [(win32gui.GetWindowText(k).replace("&", "").strip(), k) for k in _children(hwnd)
            if win32gui.IsWindowVisible(k) and "BUTTON" in win32gui.GetClassName(k).upper() and win32gui.GetWindowText(k).strip()]


def describe_native(hwnd) -> dict:
    import win32gui

    kids = _children(hwnd)
    classes = {k: win32gui.GetClassName(k) for k in kids}
    info = {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "kind": "native", "text": "", "buttons": []}
    ie = [k for k, c in classes.items() if c == "Internet Explorer_Server"]
    if ie:
        info["kind"] = "legacy-ie"
        try:
            doc = _mshtml_document(ie[0])
            info["text"] = " ".join((doc.body.innerText or "").split())[:600]
            info["buttons"] = [label for label, _ in _mshtml_buttons(doc)]
        except Exception as e:  # noqa: BLE001
            info["read_error"] = f"{type(e).__name__}: {str(e)[:150]}"
    elif any(c.startswith("Chrome_") for c in classes.values()):
        info["kind"] = "webview2"  # its content is a WebView2 page (see dialogs with view 'dialoghost')
    else:
        texts = [win32gui.GetWindowText(k).strip() for k, c in classes.items()
                 if win32gui.IsWindowVisible(k) and "BUTTON" not in c.upper() and win32gui.GetWindowText(k).strip()]
        info["text"] = " ".join(texts)[:600]
        info["buttons"] = [label for label, _ in _native_buttons(hwnd)]
    return info


def native_windows(port: int | None = None, pid: int | None = None) -> dict:
    """Power BI's own top-level windows besides the main one (dialogs, prompts, splash)."""
    import win32gui
    import win32process

    if pid:
        w = bridge.main_window(pid)
        win = (w[0], w[1], pid) if w else None
    else:
        win = pbi_window(port)
    if not win:
        return {"blocked": False, "windows": []}
    main, _, pid = win
    hwnds = []

    def cb(h, _):
        if h != main and win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] == pid:
            left, top, right, bottom = win32gui.GetWindowRect(h)
            if win32gui.GetClassName(h) != "Internet Explorer_Hidden" and right - left > 20 and bottom - top > 20:
                hwnds.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return {"blocked": not win32gui.IsWindowEnabled(main), "windows": [describe_native(h) for h in hwnds]}


def _norm(s: str) -> str:
    return " ".join((s or "").replace("’", "'").replace("‘", "'").lower().split())


def _match_label(labels: list[str], wanted: str) -> int | None:
    w = _norm(wanted)
    for i, label in enumerate(labels):
        if _norm(label) == w:
            return i
    hits = [i for i, label in enumerate(labels) if w in _norm(label)]
    return hits[0] if len(hits) == 1 else None


def click_native_button(hwnd, label: str) -> str:
    import win32con
    import win32gui

    kids = _children(hwnd)
    ie = [k for k in kids if win32gui.GetClassName(k) == "Internet Explorer_Server"]
    if ie:
        buttons = _mshtml_buttons(_mshtml_document(ie[0]))
        i = _match_label([b[0] for b in buttons], label)
        if i is None:
            raise DriverError(f"No button {label!r} in dialog. Buttons: {[b[0] for b in buttons]}")
        buttons[i][1].click()
        return buttons[i][0]
    buttons = _native_buttons(hwnd)
    i = _match_label([b[0] for b in buttons], label)
    if i is None:
        raise DriverError(f"No button {label!r} in dialog. Buttons: {[b[0] for b in buttons]}")
    win32gui.PostMessage(buttons[i][1], win32con.BM_CLICK, 0, 0)
    return buttons[i][0]


def printwindow_png(hwnd, path: Path) -> list[int]:
    """Pixels of a native dialog window. Legacy/native dialogs are outside WebView2, so DevTools
    cannot capture them; PrintWindow(PW_RENDERFULLCONTENT) is the only option for those."""
    import ctypes

    import win32gui
    import win32ui
    from PIL import Image

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hwnd_dc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)  # 2 = PW_RENDERFULLCONTENT
    info = bmp.GetInfo()
    Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1).save(path)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return [w, h]


# --------------------------------------------------------------------------- alerts

def collect_alerts(s: Session, views: tuple[str, ...] = ("report",), visual_errors: bool = True) -> dict:
    """Everything an agent must not be blind to: blocking dialogs (any technology), in-app dialogs,
    message banners, and visuals showing an error. Empty dict when all is clear."""
    out: dict = {}
    nat = native_windows(s.port)
    if nat["blocked"]:
        out["blocked"] = True
    if nat["windows"]:
        out["windows"] = nat["windows"]
    for key, page in s.floating_pages().items():
        try:
            found = page.evaluate(FLOATING_JS)
        except Exception:  # noqa: BLE001  closing while we read it
            continue
        if found["text"]:
            out.setdefault("dialogs", []).append({"view": f"floating:{key}", **found})
    for name in (*views, "dialoghost"):
        page = s.pages.get(DIALOG_HOST if name == "dialoghost" else VIEWS[name])
        if page is None or page.is_closed():
            continue
        found = page.evaluate(WEB_ALERTS_JS)
        for d in found["dialogs"]:
            out.setdefault("dialogs", []).append({"view": name, **d})
        for b in found["banners"]:
            out.setdefault("banners", []).append({"view": name, "text": b})
    if visual_errors and "report" in views:
        data = s.report.evaluate(VISUALS_JS, 200)
        errs = [{k: v[k] for k in ("index", "type", "label", "error_text")}
                for v in (data or {}).get("visuals", []) if v["error_text"] and not v["hidden"]]
        if errs:
            out["visual_errors"] = errs
    return out


def with_alerts(result: dict, s: Session, views: tuple[str, ...] = ("report",)) -> dict:
    alerts = collect_alerts(s, views)
    if alerts:
        result["alerts"] = alerts
    return result


def guard_not_blocked(s: Session, force: bool) -> None:
    """Refuse to send input while a modal dialog blocks Power BI (input would bypass it)."""
    if force:
        return
    nat = native_windows(s.port)
    if nat["blocked"]:
        names = [f"{w['title']!r} {w['buttons']}" for w in nat["windows"]]
        raise DriverError("Power BI is blocked by a dialog: " + "; ".join(names)
                        + ". Answer it with `dialog --click <button>` (or pass --force).")


# --------------------------------------------------------------------------- report helpers

def pick(items: list[dict], spec: str, what: str, primary: str, extra: tuple[str, ...] = ()) -> dict:
    """Select by index ("3") or by text: exact, then substring on `primary`, then on `extra` fields."""
    spec = spec.strip()
    if spec.isdigit():
        for x in items:
            if x["index"] == int(spec):
                return x
        raise DriverError(f"No {what} with index {spec}.")
    s = spec.lower()
    tiers = [lambda x: x[primary].lower() == s, lambda x: s in x[primary].lower()]
    tiers += [lambda x, k=k: s in str(x.get(k, "")).lower() for k in extra]
    listing = lambda xs: "; ".join(f"[{x['index']}] {x[primary]}" for x in xs[:40])  # noqa: E731
    for test in tiers:
        hits = [x for x in items if test(x)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise DriverError(f"{what} {spec!r} is ambiguous, use an index: {listing(hits)}")
    raise DriverError(f"No {what} matches {spec!r}. Available: {listing(items)}")


def goto_page(rp, spec: str | None, settle_s: float) -> dict:
    pages = rp.evaluate(PAGES_JS)
    if not pages:
        raise DriverError("No report page tabs found. Is the report loaded?")
    if spec is None:
        current = next((p for p in pages if p["selected"]), pages[0])
        settle(rp, settle_s, quiet_ms=400)
        return current
    target = pick(pages, spec, "page", "name")
    if not target["selected"]:
        rp.locator(PAGE_TAB).nth(target["index"]).click()
        settle(rp, settle_s)
        if not rp.evaluate(PAGES_JS)[target["index"]]["selected"]:
            raise DriverError(f"Could not switch to page {target['name']!r}.")
    else:
        settle(rp, settle_s, quiet_ms=400)
    return {**target, "selected": True}


def require_canvas(rp) -> dict:
    canvas = rp.evaluate(CANVAS_JS)
    if not canvas or not canvas["w"]:
        raise DriverError("Report canvas is not rendered.")
    return canvas


def visual_list(rp, text_limit: int) -> dict:
    data = rp.evaluate(VISUALS_JS, text_limit)
    if data is None:
        raise DriverError("Report canvas not found.")
    data["visuals"].sort(key=lambda v: (v["hidden"], v["box"]["y"], v["box"]["x"]))
    return data


def pick_visual(rp, spec: str) -> dict:
    visible = [v for v in visual_list(rp, 300)["visuals"] if not v["hidden"]]
    return pick(visible, spec, "visual", "label", ("title", "type", "text"))


def png_size(path: Path) -> list[int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return list(struct.unpack(">II", head[16:24]))


def slug(text: str, limit: int = 40) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "x")[:limit].strip("-")


def default_out(name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / "pbidriver_shots" / f"{stamp}_{slug(name)}"


def as_png(base: Path) -> Path:
    path = base if base.suffix.lower() == ".png" else base.with_name(base.name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def after_shot(s: Session, view: str, a, label: str) -> dict:
    """Optional capture after an interaction (--shot): canvas for the report view, page otherwise."""
    page = s.view(view)
    cdp = s.cdp(page)
    page.mouse.move(1, 1)
    settle(page, a.settle, quiet_ms=400)
    path = as_png(default_out(f"{view}-{label}"))
    if view == "report":
        with fit_canvas(page, cdp, a.settle):
            capture_target(page, cdp, "canvas", 0, 1, path)
    else:
        capture_page(page, cdp, 1, path)
    return {"file": str(path), "size": png_size(path)}


def shot_now(s: Session, page, label: str) -> dict:
    """Capture the whole page as it is right now (open menus and tooltips can overflow the canvas)."""
    path = as_png(default_out(label))
    capture_page(page, s.cdp(page), 1, path)
    return {"file": str(path), "size": png_size(path), "scope": "full"}


def page_size(port: int, page_name: str | None) -> tuple[float, float] | None:
    """The report page's own size (PBIR units, e.g. 1280 x 720) from the saved report file."""
    try:
        win = pbi_window(port)
        info = bridge.instance(win[2])
        file = (bridge.bridge_state(win[2]).get("file") if info["bridge"] else None) or info["file"]
        page = next((p for p in report_inventory(file)["pages"] if p["name"] == page_name), None)
        return (float(page["width"]), float(page["height"])) if page and page.get("width") else None
    except Exception:  # noqa: BLE001  unsaved new page, unreadable file...: fall back to canvas pixels
        return None


def tidy_canvas(s: Session, page) -> None:
    """For a clean capture: no hover header, tooltip, open menu or selection outline on any visual."""
    page.mouse.move(1, 1)
    if not native_windows(s.port)["blocked"]:
        page.keyboard.press("Escape")  # deselects the focused visual, closes dropdowns and menus
        time.sleep(0.3)
        page.mouse.move(1, 1)


def canvas_capture(s: Session, page, a, page_name: str | None, path: Path, items: list[str], clean: bool,
                   scale: float = 1, perf_ms: dict | None = None) -> dict:
    """Capture the canvas (call inside fit_canvas). With `clean`, tidy the canvas first and return the layout
    check without drawing anything; with overlay `items`, draw them and return the legend."""
    from pbidriver import layout as geometry

    if clean:
        tidy_canvas(s, page)
        settle(page, a.settle, quiet_ms=800)
    out = capture_target(page, s.cdp(page), "canvas", 0, scale, path)
    out.update(file=str(path), size=png_size(path))
    if not (clean or items):
        return out
    data = visual_list(page, 80)
    size = page_size(s.port, page_name)
    units, page_units = geometry.to_units(data["visuals"], data["canvas"], size)
    out["units"] = "page" if size else "canvas px"
    out["legend"] = geometry.legend(units, perf_ms)
    geo = None
    if clean or set(items) & {"grid", "align", "gaps", "overlap"}:
        geo = geometry.layout_check(units, page_units)
        out["layout"] = {k: v for k, v in geo.items() if k != "_gaps"}
    if items:
        geometry.draw(path, units, page_units, items, grid=getattr(a, "grid_size", 40) or 40, layout=geo,
                      perf_ms=perf_ms, threshold=getattr(a, "threshold", 500) or 500)
        out["overlay"] = items
    return out


_PERF_TYPE_ALIAS = {"table": "tableex", "matrix": "pivottable", "card(new)": "cardvisual", "newcard": "cardvisual"}


def match_perf_rows(rows: list[dict], visuals: list[dict]) -> None:
    """Set `visual_index` on Performance Analyzer rows. The analyzer names a visual by its title, or by its
    type ('Card', 'Table') when it has none; match titles first, then types that occur once on the page."""
    norm = lambda t: re.sub(r"\s+", "", (t or "").lower())  # noqa: E731
    shown = [v for v in visuals if not v["hidden"]]
    titles: dict[str, list[int]] = {}
    for v in shown:
        if v["title"]:
            titles.setdefault(v["title"], []).append(v["index"])
    untitled_types: dict[str, list[int]] = {}
    for v in shown:
        if not v["title"]:
            untitled_types.setdefault(norm(v["type"]), []).append(v["index"])
    names = [r["name"] for r in rows]
    for r in rows:
        if len(titles.get(r["name"], [])) == 1:
            r["visual_index"] = titles[r["name"]][0]
            continue
        t = norm(r["name"])
        t = _PERF_TYPE_ALIAS.get(t, t)
        if len(untitled_types.get(t, [])) == 1 and names.count(r["name"]) == 1:
            r["visual_index"] = untitled_types[t][0]


def perf_by_visual(s: Session, page, a) -> tuple[dict, list[str]]:
    """Render time per visual index (Performance Analyzer, one refresh) for the perf overlay."""
    rows = perf_summary(_perf_measure(s, page, a), getattr(a, "threshold", 500))
    match_perf_rows(rows, visual_list(page, 1)["visuals"])
    by_index = {r["visual_index"]: r["total_ms"] for r in rows
                if "visual_index" in r and r.get("total_ms") is not None}
    unmatched = [r["name"] for r in rows if "visual_index" not in r]
    return by_index, unmatched


def mouse_click(page, x: float, y: float, a) -> None:
    mods = [MODIFIER[m] for m in ("ctrl", "shift", "alt") if getattr(a, m, False)]
    for m in mods:
        page.keyboard.down(m)
    try:
        page.mouse.click(x, y, button="right" if getattr(a, "right", False) else "left",
                         click_count=2 if getattr(a, "double", False) else 1)
    finally:
        for m in reversed(mods):
            page.keyboard.up(m)


def resolve_point(page, a, view: str) -> tuple[float, float, dict]:
    """Where to click/scroll: --text (in --visual or page), --at (in --visual or viewport), else an anchor."""
    vis = pick_visual(page, a.visual) if (view == "report" and getattr(a, "visual", None)) else None
    if getattr(a, "text", None):
        scope = ["visual", vis["index"]] if vis else ["page", 0]
        hits = page.evaluate(FIND_JS, [*scope, a.text, bool(getattr(a, "exact", False))])
        if not hits:
            raise DriverError(f"No element matching {a.text!r}" + (f" in visual [{vis['index']}]" if vis else "") + ".")
        h = hits[0]
        return h["x"], h["y"], {"matched": h["label"], "role": h["role"], "visual": vis and vis["index"]}
    if getattr(a, "at", None):
        try:
            x, y = (float(v) for v in a.at.split(","))
        except ValueError:
            raise DriverError("--at expects X,Y (fractions 0-1 or pixels)") from None
        if vis:
            g = page.evaluate(GEOM_JS, ["visual", vis["index"]])["target"]
            if x <= 1 and y <= 1:
                x, y = g["x"] + x * g["w"], g["y"] + y * g["h"]
            else:
                x, y = g["x"] + x, g["y"] + y
        return x, y, {"visual": vis and vis["index"]}
    anchor = page.evaluate(ANCHOR_JS, ["visual" if vis else "auto", vis["index"] if vis else 0])
    if not anchor:
        raise DriverError("Target is not visible on screen.")
    return anchor["x"], anchor["y"], {"visual": vis and vis["index"]}


# --------------------------------------------------------------------------- commands

def cmd_launch(a) -> dict:
    file = Path(a.file).expanduser().resolve()
    if not file.exists():
        raise DriverError(f"File not found: {file}")
    if file.suffix.lower() not in (".pbix", ".pbip", ".pbit"):
        raise DriverError("Expected a .pbix, .pbip or .pbit file.")
    if _http_json(a.port, "/json/version"):
        raise DriverError(f"Port {a.port} already has a DevTools endpoint. Run `status`, or pass a different --port.")

    profile = PROFILE_ROOT / f"webview2-{a.port}"
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # A private WebView2 profile gives this instance its own browser process, so the DevTools
    # flag applies even while other Power BI windows (started normally) are open.
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(profile)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={a.port}"
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(find_pbi_exe()), str(file)], env=env, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t0 = time.time()
    _wait_for(lambda: _http_json(a.port, "/json/version"), 90,
              f"DevTools port {a.port} never opened. Another program may hold the port, or the profile folder is in use.")
    remaining = lambda: max(5.0, a.timeout - (time.time() - t0))  # noqa: E731
    # Startup prompts (file recovery, security warnings...) can appear before the report loads.
    deadline = time.time() + remaining()
    while not _has_target(a.port, VIEWS["report"]):
        nat = native_windows(a.port)
        if nat["blocked"] and nat["windows"]:
            return {"port": a.port, "file": str(file), "loaded": False, "seconds": round(time.time() - t0, 1),
                    "alerts": {"blocked": True, "windows": nat["windows"]},
                    "hint": "Answer the dialog with `dialog --click <button>`, then run `status`."}
        if time.time() > deadline:
            raise DriverError("Report view did not load in time.")
        time.sleep(1)
    with pbi_session(a.port) as s:
        rp = s.report
        # Wait for the page tabs, but stop early when Power BI shows an error or a prompt instead
        # (e.g. "Something went wrong / Failed to load the report"): an agent must see that at once.
        deadline = time.time() + remaining()
        while time.time() < deadline:
            if rp.query_selector(PAGE_TAB):
                break
            found = collect_alerts(s, visual_errors=False)
            if found.get("blocked") or found.get("dialogs"):
                time.sleep(2)  # give a slow load a moment before reporting
                if not rp.query_selector(PAGE_TAB):
                    break
            time.sleep(1)
        settle(rp, a.settle)
        result = {"port": a.port, "file": str(file), "loaded": bool(rp.evaluate(PAGES_JS)),
                  "seconds": round(time.time() - t0, 1), "canvas": rp.evaluate(CANVAS_JS), "pages": rp.evaluate(PAGES_JS)}
        win = pbi_window(a.port)
        result.update(pid=win[2] if win else None, window_title=win[1] if win else None)
        try:
            result["model_port"] = bridge.instance(result["pid"])["model_port"] if result["pid"] else None
        except (DriverError, bridge.BridgeError):
            pass
        result = with_alerts(result, s)
        if any("refresh now" in b["text"].lower() for b in result.get("alerts", {}).get("banners", [])):
            result["next"] = ("Data needs a refresh (see alerts.banners): run `pbidriver refresh --sync`"
                              if file.suffix.lower() == ".pbip" else
                              "Data needs a refresh (see alerts.banners): run `pbidriver refresh`")
        return result


def _bridge_info(pid: int) -> dict:
    """Unsaved state etc. from the Desktop Bridge, when this Power BI has one."""
    info = bridge.instance(pid)
    out = {"bridge": info["bridge"], "model_port": info["model_port"]}
    if info["bridge"]:
        try:
            st = bridge.bridge_state(pid)
            out.update(file=st["file"], unsaved=st["unsaved"])
        except bridge.BridgeError as e:
            out["bridge_error"] = str(e)
    return out


def cmd_status(a) -> dict:
    version = _http_json(a.port, "/json/version")
    if not version or (a.pid and (pbi_window(a.port) or (0, 0, 0))[2] != a.pid):
        found = bridge.instances()
        if not found:
            return {"running": False, "port": a.port,
                    "hint": "Start an instance with: pbidriver launch <file.pbix|file.pbip>"}
        pid = resolve_pid(a)
        import win32gui

        info = bridge.instance(pid)
        win = bridge.main_window(pid)
        result = {"running": True, "devtools": False, "pid": pid, "window_title": info["window_title"],
                  "file": info["file"], "minimized": bool(win and win32gui.IsIconic(win[0])), **_bridge_info(pid)}
        nat = native_windows(pid=pid)
        if nat["blocked"] or nat["windows"]:
            result["alerts"] = {k: v for k, v in nat.items() if v}
        result["hint"] = ("Not started by pbidriver: page/visual shots, reload, dax and model work through the Desktop "
                          "Bridge; for clicks, slicers and other views, open the file with `launch`.")
        return result
    import win32gui

    win = pbi_window(a.port)
    with pbi_session(a.port) as s:
        pages = s.report.evaluate(PAGES_JS)
        result = {
            "running": True, "devtools": True, "port": a.port, "engine": version.get("Browser"),
            "pid": win[2] if win else None, "window_title": win[1] if win else None, "file": report_file(a.port),
            "minimized": bool(win and win32gui.IsIconic(win[0])),
            "current_page": next((p["name"] for p in pages if p["selected"]), None),
            "page_count": len(pages), "canvas": s.report.evaluate(CANVAS_JS),
            "views": [v for v, url in VIEWS.items() if url in s.pages],
        }
        if win:
            result.update({k: v for k, v in _bridge_info(win[2]).items() if k != "file" or v})
        return with_alerts(result, s)


def cmd_instances(a) -> dict:
    found = bridge.instances()
    for i in found:
        if i["bridge"]:
            try:
                i.update(bridge.bridge_state(i["pid"]))
            except bridge.BridgeError as e:
                i["bridge_error"] = str(e)
    return {"count": len(found), "instances": found}


def cmd_pages(a) -> dict:
    with pbi_session(a.port) as s:
        return {"pages": s.report.evaluate(PAGES_JS)}


def cmd_alerts(a) -> dict:
    with pbi_session(a.port) as s:
        return {"alerts": collect_alerts(s, tuple(VIEWS) if a.all_views else ("report",))}


def cmd_visuals(a) -> dict:
    with visible_window(a.port), pbi_session(a.port) as s:
        rp = s.report
        if not a.all_pages:
            page = goto_page(rp, a.page, a.settle)
            data = visual_list(rp, a.text_limit)
            return with_alerts({"page": page["name"], "canvas": data["canvas"], "count": len(data["visuals"]),
                                "visuals": data["visuals"]}, s)
        original = goto_page(rp, None, a.settle)
        out = []
        for p in rp.evaluate(PAGES_JS):
            goto_page(rp, str(p["index"]), a.settle)
            vs = [v for v in visual_list(rp, a.text_limit)["visuals"] if not v["hidden"]]
            out.append({"page": p["name"], "hidden_page": p["hidden"], "count": len(vs), "visuals": vs})
        goto_page(rp, str(original["index"]), a.settle)
        types: dict[str, dict] = {}
        for p in out:
            for v in p["visuals"]:
                t = types.setdefault(v["type"], {"count": 0, "pages": {}})
                t["count"] += 1
                t["pages"][p["page"]] = t["pages"].get(p["page"], 0) + 1
        return {"source": "live", "types": dict(sorted(types.items(), key=lambda kv: -kv[1]["count"])), "pages": out}


def cmd_inventory(a) -> dict:
    file = a.file or report_file(a.port)
    if not file:
        try:
            pid = resolve_pid(a)
            info = bridge.instance(pid)
            file = (bridge.bridge_state(pid)["file"] if info["bridge"] else None) or info["file"]
        except (DriverError, bridge.BridgeError):
            file = None
    if not file:
        raise DriverError("Could not tell which file the instance has open; pass --file <report.pbix|.pbip>.")
    inv = report_inventory(file)
    inv["source"] = "file (last saved state)"
    if a.type:
        want = a.type.lower()
        for p in inv["pages"]:
            p["visuals"] = [v for v in p["visuals"] if want in v["type"].lower()]
        inv["pages"] = [p for p in inv["pages"] if p["visuals"]]
    if a.summary:
        inv.pop("pages")
    return inv


def _inventory_visuals(page: dict) -> list[dict]:
    out = []
    for i, v in enumerate(page["visuals"]):
        if v["hidden"] or v["type"] == "group" or not v["w"] or not v["h"]:
            continue
        out.append({**v, "index": i, "label": v.get("title") or v.get("text") or v["type"]})
    return out


def cmd_shot_bridge(a) -> dict:
    """Capture through Microsoft's Desktop Bridge: no DevTools needed, any running instance.
    Pages and visuals are located from the report file (its last saved state)."""
    if a.view != "report" or a.full:
        raise DriverError("Through the Desktop Bridge only report pages and visuals can be captured "
                        "(other views and --full need an instance started with `launch`).")
    pid = resolve_pid(a)
    state = bridge.bridge_state(pid)
    if not state["file"]:
        raise DriverError("This Power BI instance has no file open.")
    inv = report_inventory(state["file"])
    pages = [{**p, "index": p["index"]} for p in inv["pages"]]
    note = []
    if a.page:
        page = pick(pages, a.page, "page", "name")
    else:
        page = next((p for p in pages if not p["hidden"]), pages[0])
        note.append(f"No --page given; captured the first page ({page['name']!r}).")
    v2 = "report.snapshot.capture/v2" in bridge.bridge_methods(pid)
    base = Path(a.out).expanduser().resolve() if a.out else default_out(page["name"])
    full = {"x": 0, "y": 0, "width": page["width"], "height": page["height"]}
    result: dict = {"via": "desktop-bridge", "pid": pid, "page": page["name"]}
    if state["unsaved"] and (a.visual is not None or a.all_visuals):
        note.append("The report has unsaved changes; visual positions come from the saved file and may be off.")
    if (a.visual is not None or a.all_visuals) and not v2:
        raise DriverError("This Power BI build has no report.snapshot.capture/v2, so the Bridge can only capture whole pages.")

    def grab(region, path: Path):
        path.write_bytes(bridge.bridge_snapshot(pid, page["id"], a.scale, region))
        return {"file": str(path), "size": png_size(path)}

    with visible_window(pid=pid):
        if a.all_visuals:
            out_dir = base if not base.suffix else base.with_suffix("")
            out_dir.mkdir(parents=True, exist_ok=True)
            files = []
            for v in _inventory_visuals(page):
                region = {"x": v["x"], "y": v["y"], "width": v["w"], "height": v["h"]}
                path = out_dir / f"v{v['index']:02d}_{slug(v['type'], 24)}_{slug(v['label'])}.png"
                files.append({**grab(region, path), "index": v["index"], "type": v["type"], "label": v["label"]})
            result.update(scope="all-visuals", dir=str(out_dir), files=files)
        elif a.visual is not None:
            v = pick(_inventory_visuals(page), a.visual, "visual", "label", ("type", "id"))
            region = {"x": v["x"], "y": v["y"], "width": v["w"], "height": v["h"]}
            path = as_png(base if a.out else base.with_name(f"{base.name}_v{v['index']:02d}_{slug(v['label'])}"))
            result.update(scope="visual", **grab(region, path),
                          visual={k: v[k] for k in ("index", "id", "type", "label", "fields")})
        else:
            result.update(scope="page", **grab(full if v2 else None, as_png(base)))
    if note:
        result["note"] = " ".join(note)
    return result


def _use_bridge(a) -> bool:
    """Bridge when asked, when there is no DevTools instance, or when --pid names another instance."""
    if a.bridge:
        return True
    if not _http_json(a.port, "/json/version"):
        return bool(a.pid or bridge.instances())
    if a.pid:
        win = pbi_window(a.port)
        return not win or win[2] != a.pid
    return False


def cmd_shot(a) -> dict:
    if _use_bridge(a):
        return cmd_shot_bridge(a)
    with visible_window(a.port) as restored, pbi_session(a.port) as s:
        base = Path(a.out).expanduser().resolve() if a.out else None

        if a.view != "report":
            page = s.view(a.view)
            settle(page, a.settle, quiet_ms=400)
            path = as_png(base or default_out(a.view))
            capture_page(page, s.cdp(page), a.scale, path)
            return with_alerts({"view": a.view, "scope": "view", "restored_from_minimized": restored,
                                "file": str(path), "size": png_size(path)}, s, (a.view,))

        from pbidriver import layout as geometry

        try:
            items = geometry.expand(a.overlay) or (["index", "type"] if a.annotate else [])
        except ValueError as e:
            raise DriverError(str(e)) from e
        if a.clean and items:
            raise DriverError("--clean captures without overlays; drop --annotate/--overlay (the result still "
                              "has the legend and a layout check).")
        if items and (a.visual is not None or a.all_visuals or a.full):
            raise DriverError("Overlays are drawn on canvas captures only; drop --visual/--all-visuals/--full.")
        rp, cdp = s.report, s.cdp(s.report)
        if restored:
            settle(rp, a.settle)
        page = goto_page(rp, a.page, a.settle)
        require_canvas(rp)
        perf_ms, unmatched = (perf_by_visual(s, rp, a) if "perf" in items else (None, []))
        # Park the (synthetic) pointer on the title bar so no hover headers/tooltips show on visuals.
        rp.mouse.move(1, 1)
        settle(rp, a.settle, quiet_ms=300)
        base = base or default_out(page["name"])
        result: dict = {"view": "report", "page": page["name"], "restored_from_minimized": restored}
        if unmatched:
            result["perf_unmatched"] = unmatched  # Performance Analyzer names these by an ambiguous or missing title

        if a.full:
            path = as_png(base)
            capture_page(rp, cdp, a.scale, path)
            result.update(scope="full", file=str(path), size=png_size(path))
            return with_alerts(result, s)

        with fit_canvas(rp, cdp, a.settle) as override:
            result["viewport_override"] = override
            if a.all_visuals:
                out_dir = base if not base.suffix else base.with_suffix("")
                out_dir.mkdir(parents=True, exist_ok=True)
                files = []
                for v in visual_list(rp, 120)["visuals"]:
                    if v["hidden"]:
                        continue
                    path = out_dir / f"v{v['index']:02d}_{slug(v['type'], 24)}_{slug(v['label'])}.png"
                    capture_target(rp, cdp, "visual", v["index"], a.scale, path)
                    files.append({"file": str(path), "size": png_size(path), "index": v["index"],
                                  "type": v["type"], "label": v["label"], "error_text": v["error_text"]})
                result.update(scope="all-visuals", dir=str(out_dir), files=files)
            elif a.visual is not None:
                v = pick_visual(rp, a.visual)
                path = as_png(base if a.out else base.with_name(f"{base.name}_v{v['index']:02d}_{slug(v['label'])}"))
                result.update(capture_target(rp, cdp, "visual", v["index"], a.scale, path))
                result.update(scope="visual", file=str(path), size=png_size(path),
                              visual={k: v[k] for k in ("index", "type", "label", "box", "error_text", "text")})
            else:
                path = as_png(base)
                result["scope"] = "canvas"
                result.update(canvas_capture(s, rp, a, page["name"], path, items, a.clean, a.scale, perf_ms))
                if a.clean:
                    result["clean"] = True
        return with_alerts(result, s)


def _native_dialog(a, nat: dict, s: Session | None = None) -> dict:
    w = nat["windows"][0]
    if a.click:
        pressed = click_native_button(w["hwnd"], a.click)
        time.sleep(1)
        result = {"dialog": w["title"], "kind": w["kind"], "pressed": pressed}
        return with_alerts(result, s) if s else result
    if a.shot:
        path = as_png(Path(a.out).expanduser().resolve() if a.out else default_out(f"dialog-{w['title']}"))
        size = printwindow_png(w["hwnd"], path)
        return {"dialog": w["title"], "kind": w["kind"], "file": str(path), "size": size,
                "note": "native/legacy dialog: captured with PrintWindow (not reachable through DevTools)"}
    return {"blocked": nat["blocked"], "dialog": w, "others": nat["windows"][1:]}


def cmd_dialog(a) -> dict:
    devtools_pid = (pbi_window(a.port) or (0, 0, None))[2] if _http_json(a.port, "/json/version") else None
    if devtools_pid is None or (a.pid and a.pid != devtools_pid):
        # No DevTools for this instance: native and legacy dialogs still work through Windows.
        pid = resolve_pid(a)
        nat = native_windows(pid=pid)
        if nat["windows"] and nat["windows"][0]["kind"] != "webview2":
            return _native_dialog(a, nat)
        if nat["windows"]:
            raise DriverError("This dialog is an in-app (WebView2) one; answering it needs an instance started with `launch`.")
        return {"blocked": nat["blocked"], "dialog": None}
    with visible_window(a.port), pbi_session(a.port) as s:
        nat = native_windows(a.port)
        # Topmost first: a native/legacy modal, then the WebView2 dialog host, then the chosen view.
        # (A "webview2" window is the host of an in-app dialog; that one is answered through DevTools.)
        native = [w for w in nat["windows"] if w["kind"] in ("native", "legacy-ie")]
        if native:
            return _native_dialog(a, {**nat, "windows": native}, s)
        s.refresh_pages()

        for key, page in s.floating_pages().items():  # legacy floating dialogs, e.g. Refresh
            d = page.evaluate(FLOATING_JS)
            if not d["text"]:
                continue
            name = f"floating:{key}"
            if a.click:
                hits = [h for h in (page.evaluate(FIND_JS, ["page", 0, a.click, False]) or [])
                        if h["tag"] in ("button", "input", "a", "span", "div") or h["role"] == "button"]
                if not hits:
                    raise DriverError(f"No button {a.click!r} in dialog. Buttons: {d['buttons']}")
                page.mouse.click(hits[0]["x"], hits[0]["y"])
                time.sleep(1)
                return with_alerts({"dialog_view": name, "pressed": hits[0]["label"]}, s, (a.view,))
            if a.shot:
                path = as_png(Path(a.out).expanduser().resolve() if a.out else default_out("dialog-floating"))
                capture_page(page, s.cdp(page), 1, path)
                return {"dialog_view": name, "file": str(path), "size": png_size(path)}
            return {"blocked": nat["blocked"], "dialog_view": name, "dialog": d}
        for name in ("dialoghost", a.view):
            page = s.pages.get(DIALOG_HOST if name == "dialoghost" else VIEWS[name])
            if page is None:
                continue
            found = page.evaluate(WEB_ALERTS_JS)["dialogs"]
            if not found:
                continue
            d = found[-1]
            if a.click:
                hits = [h for h in (page.evaluate(FIND_JS, ["dialog", 0, a.click, False]) or [])
                        if h["tag"] in ("button", "span", "div") or h["role"] == "button"]
                if not hits:
                    raise DriverError(f"No button {a.click!r} in dialog. Buttons: {d['buttons']}")
                page.mouse.click(hits[0]["x"], hits[0]["y"])
                settle(page, a.settle, quiet_ms=400)
                return with_alerts({"dialog_view": name, "pressed": hits[0]["label"]}, s, (a.view,))
            if a.shot:
                el = page.locator("mat-dialog-container, [role=dialog], [role=alertdialog], [aria-modal=true]").last
                bb = el.bounding_box()
                path = as_png(Path(a.out).expanduser().resolve() if a.out else default_out(f"dialog-{name}"))
                path.write_bytes(_grab(s.cdp(page), bb["x"], bb["y"], bb["width"], bb["height"], 1))
                return {"dialog_view": name, "file": str(path), "size": png_size(path)}
            return {"blocked": False, "dialog_view": name, "dialog": d}
        return {"blocked": nat["blocked"], "dialog": None}


def _interaction(a, action, shot_live: bool = False):
    """Common frame for input commands: visible window, not blocked, canvas fitted, settle, alerts, --shot.
    shot_live: capture the full page right after the action, before anything moves (menus, tooltips)."""
    with visible_window(a.port), pbi_session(a.port) as s:
        guard_not_blocked(s, a.force)
        page = s.view(a.view)
        if a.view == "report":
            goto_page(page, a.page, a.settle)
        with (fit_canvas(page, s.cdp(page), a.settle) if a.view == "report" else _null()):
            result = action(s, page)
            if not shot_live:
                settle(page, a.settle, quiet_ms=600)
        result["view"] = a.view
        if a.shot and "shot" not in result and not shot_live:
            result["shot"] = after_shot(s, a.view, a, a.command)
        return with_alerts(result, s, (a.view,))


@contextmanager
def _null():
    yield None


def cmd_click(a) -> dict:
    def act(s, page):
        x, y, info = resolve_point(page, a, a.view)
        mouse_click(page, x, y, a)
        return {"clicked": {"x": round(x), "y": round(y), **info}}
    return _interaction(a, act)


def cmd_scroll(a) -> dict:
    def act(s, page):
        x, y, info = resolve_point(page, a, a.view)
        page.mouse.move(x, y)
        # Separate axes (a combined event scrolls only sideways in Power BI grids), and send
        # horizontal scrolling as 120 px notches: table visuals move one column per wheel event.
        if a.dx:
            for _ in range(max(1, round(abs(a.dx) / 120))):
                page.mouse.wheel(120 if a.dx > 0 else -120, 0)
        if a.dy:
            page.mouse.wheel(0, a.dy)
        return {"scrolled": {"dx": a.dx, "dy": a.dy, "at": [round(x), round(y)], **info}}
    return _interaction(a, act)


def cmd_type(a) -> dict:
    def act(s, page):
        info = {}
        if a.visual or a.into:
            a.text = a.into
            x, y, info = resolve_point(page, a, a.view)
            page.mouse.click(x, y)
        page.keyboard.type(a.value, delay=20)
        if a.press:
            page.keyboard.press(a.press)
        return {"typed": a.value, "pressed": a.press, **({"into": info} if info else {})}
    return _interaction(a, act)


def cmd_key(a) -> dict:
    def act(s, page):
        for k in a.keys:
            page.keyboard.press(k)
        return {"pressed": a.keys}
    return _interaction(a, act)


class SlicerList:
    """A slicer's option list. Long lists are virtualized (only ~visible rows exist in the DOM),
    so reading every option or reaching one means wheel-scrolling the list itself."""

    MAX_STEPS = 80

    def __init__(self, page, index: int):
        self.page, self.index = page, index

    def state(self) -> dict:
        return self.page.evaluate(SLICER_JS, self.index)

    def _wheel(self, state: dict, dy: float) -> None:
        items = state["items"]
        self.page.mouse.move(sum(i["x"] for i in items) / len(items), sum(i["y"] for i in items) / len(items))
        self.page.mouse.wheel(0, dy)
        settle(self.page, 5, quiet_ms=250)

    def to_top(self) -> dict:
        state = self.state()
        if state["items"]:
            self._wheel(state, -100000)
        return self.state()

    def scan(self) -> dict[str, bool]:
        """label -> selected, for every option (scrolls through, then back to the top)."""
        state = self.to_top()
        seen: dict[str, bool] = {}
        for _ in range(self.MAX_STEPS):
            new = [i for i in state["items"] if i["label"] not in seen]
            for i in state["items"]:
                seen[i["label"]] = i["selected"]
            if not new:
                break
            self._wheel(state, 240)
            state = self.state()
        self.to_top()
        return seen

    def reveal(self, label: str) -> dict:
        """Scroll until `label` is rendered; returns its item (with fresh coordinates)."""
        state = self.to_top()
        seen: set[str] = set()
        for _ in range(self.MAX_STEPS):
            hit = next((i for i in state["items"] if i["label"] == label), None)
            if hit:
                return hit
            new = {i["label"] for i in state["items"]} - seen
            if not new:
                break
            seen |= new
            self._wheel(state, 240)
            state = self.state()
        raise DriverError(f"Option {label!r} not found while scrolling the slicer.")


def cmd_slicer(a) -> dict:
    def act(s, page):
        v = pick_visual(page, a.visual)
        sl = SlicerList(page, v["index"])
        state = sl.state()
        opened = False
        if state["dropdown"] and not state["expanded"]:
            page.mouse.click(state["combo"]["x"], state["combo"]["y"])
            settle(page, a.settle, quiet_ms=400)
            state, opened = sl.state(), True
        if not state["items"]:
            raise DriverError(f"Visual [{v['index']}] ({v['type']}) exposes no selectable items. Use `click --visual {v['index']} --text ...`.")
        full = sl.scan()
        labels = list(full)
        target = None
        if a.clear:
            target = set()
        elif a.select:
            target = set()
            for want in a.select:
                i = _match_label(labels, want)
                if i is None:
                    raise DriverError(f"No option {want!r} in slicer. Options: {labels}")
                target.add(labels[i])
        if target is not None:
            # Converge on the target set; works for single-select, CTRL-multi-select and plain multi-select slicers.
            for _ in range(2 * len(labels) + 4):
                sel = {k for k, on in full.items() if on}
                if sel == target:
                    break
                missing, extra = sorted(target - sel), sorted(sel - target)
                label, mods = (missing[0], [] if not (sel & target) else ["Control"]) if missing else (extra[0], ["Control"])
                item = sl.reveal(label)
                for m in mods:
                    page.keyboard.down(m)
                page.mouse.click(item["x"], item["y"])
                for m in mods:
                    page.keyboard.up(m)
                settle(page, a.settle, quiet_ms=400)
                full = sl.scan()
        result = {"visual": {"index": v["index"], "type": v["type"], "label": v["label"]},
                  "options": labels, "selected": [k for k, on in full.items() if on]}
        state = sl.state()
        if target is not None and set(result["selected"]) != target:
            result["warning"] = "Selection did not end up exactly as requested; check `selected`."
        if state["dropdown"] and state["expanded"] and (opened or target is not None):
            page.mouse.click(state["combo"]["x"], state["combo"]["y"])  # close the popup again
            settle(page, a.settle, quiet_ms=400)
            result["header"] = page.evaluate(SLICER_JS, v["index"])["header"]
        return result
    return _interaction(a, act)


# --------------------------------------------------------------------------- reading visual data

def _points_table(points: list, max_rows: int) -> tuple[list, list, int]:
    """Data points -> one table. Fields present in every point (categories, series) form the row
    key; points sharing a key with disjoint other fields (e.g. one per measure) merge into one row."""
    cols: list[str] = []
    for p in points:
        for name, _ in p:
            if name not in cols:
                cols.append(name)
    common = [c for c in cols if all(any(n == c for n, _ in p) for p in points)]
    merged: dict[tuple, dict] = {}
    for p in points:
        d = dict(p)
        key = tuple(d.get(c) for c in common)
        row = merged.get(key)
        if row is not None and not (set(d) - set(common)) & (set(row) - set(common)):
            row.update(d)
        else:
            merged[key if row is None else key + (len(merged),)] = d
    rows = [[d.get(c) for c in cols] for d in merged.values()]
    return cols, rows[:max_rows], len(rows)


def _wheel(page, anchor: dict, dx: float = 0, dy: float = 0, events: int = 1) -> None:
    """Wheel over a point. Power BI grids treat an event with both deltas as horizontal, and move
    one column per horizontal event whatever its size, so axes are separate and columns are counted."""
    page.mouse.move(anchor["x"], anchor["y"])
    for _ in range(events):
        page.mouse.wheel(dx, dy)
    settle(page, 5, quiet_ms=250)


def read_grid(page, index: int, max_rows: int) -> dict | None:
    """Every cell of a table/matrix. Grids are virtualized (only on-screen cells exist), so this
    wheel-scrolls through them, collecting cells by aria row/column index, then scrolls back."""
    g = page.evaluate(GRID_JS, index)
    if not g:
        return None
    cells: dict[tuple[int, int], tuple[str, str]] = {}

    def absorb(state) -> int:
        n = len(cells)
        for r, c, text, role in (state or {}).get("cells", []):
            cells.setdefault((r, c), (text, role))
        return len(cells) - n

    anchor = g["anchor"]
    ncols = g["colcount"] or 0
    max_col = lambda state: max([c for _, c, _, _ in state["cells"]] or [0])  # noqa: E731

    def home_columns(home_max: int | None = None):
        """Scroll fully left; with home_max, keep going until no column past it is rendered."""
        _wheel(page, anchor, dx=-120, events=ncols + 5)
        for _ in range(6):
            if home_max is None:
                return
            state = page.evaluate(GRID_JS, index)
            if max_col(state) <= home_max:
                return
            time.sleep(0.2)
            _wheel(page, anchor, dx=-120, events=max_col(state) - home_max + 2)

    def home_rows():
        _wheel(page, anchor, dy=-10_000_000)

    home_columns()
    home_rows()
    first = page.evaluate(GRID_JS, index)
    absorb(first)
    home_max = max_col(first)
    visible_cols = len({c for _, c, _, _ in first["cells"]})
    needs_h = bool(ncols and visible_cols < ncols)
    step_cols = max(1, visible_cols - 3)
    step_y = max(60, g["height"] * 0.7)
    data_rows = lambda: {r for (r, _), (_, role) in cells.items() if role != "c"}  # noqa: E731
    for _ in range(500):
        if needs_h:
            for _ in range(ncols // step_cols + 2):
                _wheel(page, anchor, dx=120, events=step_cols)
                if not absorb(page.evaluate(GRID_JS, index)):
                    break
            home_columns(home_max)
        # (a pinned Total row already carries the last row index, so count rows seen instead)
        if len(data_rows()) >= max_rows or (g["rowcount"] and len({r for r, _ in cells}) >= g["rowcount"]):
            break
        _wheel(page, anchor, dy=step_y)
        if not absorb(page.evaluate(GRID_JS, index)):
            break
    home_rows()
    page.mouse.move(1, 1)  # don't leave a tooltip up

    ncols = max([c for _, c in cells] + [g["colcount"] or 0])
    by_row: dict[int, dict[int, tuple[str, str]]] = {}
    for (r, c), cell in cells.items():
        by_row.setdefault(r, {})[c] = cell
    header, body = [], []
    for r in sorted(by_row, key=lambda r: (r < 0, abs(r))):
        row = by_row[r]
        values = [row[c][0] if c in row and row[c][0] != "" else None for c in range(1, ncols + 1)]
        (header if any(role == "c" for _, role in row.values()) else body).append(values)
    # Tables have an accessibility column of row-selection checkboxes ("Row Selection" / "Select Row"): not data.
    if header and header[-1] and header[-1][0] == "Row Selection" and all(
            v[0] in (None, "Select Row") for v in body):
        header = [h[1:] for h in header]
        body = [v[1:] for v in body]
    total = (g["rowcount"] - len(header)) if g["rowcount"] else len(body)
    out = {"kind": "grid", "columns": header[-1] if header else None, "rows": body[:max_rows],
           "row_count": total, "truncated": total > min(len(body), max_rows)}
    if out["truncated"]:
        out["note"] = ("row_count is what Power BI has loaded so far (large tables load in windows). "
                       "For every row, query the visual's fields with `dax`.")
    if len(header) > 1:
        out["header_rows"] = header
    return out


def read_slicer(page, v: dict, settle_s: float, full: bool) -> dict | None:
    sl = SlicerList(page, v["index"])
    state = sl.state()
    if not full:  # quick look: what is rendered, without opening or scrolling
        if not state["items"] and not state["dropdown"]:
            return None
        return {"kind": "slicer", "header": state["header"], "visible_options": [i["label"] for i in state["items"]],
                "selected": [i["label"] for i in state["items"] if i["selected"]], "complete": False}
    opened = False
    if state["dropdown"] and not state["expanded"]:
        page.mouse.click(state["combo"]["x"], state["combo"]["y"])
        settle(page, settle_s, quiet_ms=400)
        state, opened = sl.state(), True
    if not state["items"]:
        return None
    options = sl.scan()
    if opened:
        page.mouse.click(state["combo"]["x"], state["combo"]["y"])
        settle(page, settle_s, quiet_ms=400)
    return {"kind": "slicer", "header": sl.state()["header"], "options": list(options),
            "selected": [k for k, on in options.items() if on], "complete": True}


def read_visual(page, v: dict, max_rows: int, settle_s: float, deep: bool) -> dict:
    base = {"index": v["index"], "type": v["type"], "label": v["label"]}
    data = page.evaluate(READ_JS, v["index"]) or {}
    if data.get("points"):
        cols, rows, total = _points_table(data["points"], max_rows)
        return {**base, "kind": "points", "columns": cols, "rows": rows, "row_count": total, "truncated": total > max_rows}
    if "slicer" in v["type"].lower():
        sl = read_slicer(page, v, settle_s, deep)
        if sl:
            return {**base, **sl}
    if data.get("cards"):
        return {**base, "kind": "card", "values": [{"name": n, "value": val} for n, val in data["cards"]]}
    if data.get("grid"):
        g = read_grid(page, v["index"], max_rows)
        if g and any(x is not None for row in g["rows"] for x in row):
            return {**base, **g}
    if v.get("custom") or data.get("iframe"):
        return {**base, "kind": "custom", "text": data.get("text") or None,
                "note": "Custom visuals render in a sandbox, so their data can't be read from the page; "
                        "query the fields from `inventory` with `dax` instead."}
    if data.get("text"):
        return {**base, "kind": "text", "text": data["text"]}
    return {**base, "kind": "empty"}


def _current_page(page) -> str | None:
    return next((p["name"] for p in page.evaluate(PAGES_JS) if p["selected"]), None)


def cmd_read(a) -> dict:
    def act(s, page):
        if a.visual:
            v = pick_visual(page, a.visual)
            return {"page": _current_page(page), "visual": read_visual(page, v, a.max_rows or 200, a.settle, True)}
        visuals = [v for v in visual_list(page, 200)["visuals"] if not v["hidden"]]
        out = [read_visual(page, v, a.max_rows or 50, a.settle, False) for v in visuals]
        return {"page": _current_page(page), "visuals": [o for o in out if o["kind"] != "empty"]}
    return _interaction(a, act)


# --------------------------------------------------------------------------- tooltips, menus, panes

def cmd_hover(a) -> dict:
    def act(s, page):
        x, y, info = resolve_point(page, a, a.view)
        page.mouse.move(x - 15, y - 15)
        page.mouse.move(x, y, steps=5)
        tip, deadline = None, time.time() + 4
        while time.time() < deadline and not tip:
            time.sleep(0.25)
            tip = page.evaluate(TOOLTIP_JS)
        if tip:
            time.sleep(0.4)  # let it finish rendering
            tip = page.evaluate(TOOLTIP_JS) or tip
        result = {"hovered": {"x": round(x), "y": round(y), **info}, "tooltip": tip}
        if not tip:
            result["note"] = "No tooltip appeared at this point (tooltips may be off for this visual)."
        if a.shot:
            result["shot"] = shot_now(s, page, "hover")
        page.mouse.move(1, 1)
        return result
    return _interaction(a, act, shot_live=True)


def _menus(page, wait: float = 2.5) -> list:
    deadline = time.time() + wait
    while True:
        menus = page.evaluate(MENU_JS)
        if menus or time.time() > deadline:
            return menus
        time.sleep(0.2)


def _close_menus(page) -> None:
    for _ in range(5):
        if not page.evaluate(MENU_JS):
            return
        page.keyboard.press("Escape")
        time.sleep(0.3)


def cmd_menu(a) -> dict:
    def act(s, page):
        if a.more:
            if not a.visual:
                raise DriverError("--more needs --visual.")
            v = pick_visual(page, a.visual)
            anchor = page.evaluate(ANCHOR_JS, ["visual", v["index"]])
            page.mouse.move(anchor["x"], anchor["y"], steps=3)
            time.sleep(0.8)  # the visual header appears on hover
            hits = page.evaluate(FIND_JS, ["visual", v["index"], "More options", True])
            if not hits:
                raise DriverError("This visual shows no 'More options' button (its header may be turned off).")
            page.mouse.click(hits[0]["x"], hits[0]["y"])
            info = {"visual": v["index"], "via": "more-options"}
        else:
            x, y, info = resolve_point(page, a, a.view)
            page.mouse.click(x, y, button="right")
        menus = _menus(page)
        if not menus:
            raise DriverError("No menu opened at that point.")
        result: dict = {"opened": info, "items": [{k: i[k] for k in ("label", "disabled", "submenu")} for i in menus[0]]}
        if a.choose:
            path = [p.strip() for p in a.choose.split(">") if p.strip()]
            chosen: list[str] = []
            for depth, want in enumerate(path):
                menus = _menus(page)
                if depth >= len(menus):
                    raise DriverError(f"Submenu level {depth + 1} did not open (after {chosen}).")
                items = menus[depth]
                i = _match_label([x["label"] for x in items], want)
                if i is None:
                    raise DriverError(f"No menu item {want!r}. Items: {[x['label'] for x in items]}")
                item = items[i]
                if item["disabled"]:
                    raise DriverError(f"Menu item {item['label']!r} is disabled.")
                page.mouse.move(item["x"], item["y"], steps=3)
                time.sleep(0.3)
                page.mouse.click(item["x"], item["y"])
                time.sleep(0.6)
                chosen.append(item["label"])
            result["chosen"] = chosen
            leftover = page.evaluate(MENU_JS)
            if leftover:  # chose a submenu parent: report what it offers
                result["submenu_items"] = [x["label"] for x in leftover[-1]]
            settle(page, a.settle, quiet_ms=600)
        if a.shot:
            result["shot"] = shot_now(s, page, "menu")
        _close_menus(page)
        return result
    return _interaction(a, act, shot_live=True)


def _ribbon(page, label: str | None = None) -> dict:
    return page.evaluate(RIBBON_JS, label)


def ensure_toggle(page, tab: str, label: str, want: bool) -> bool:
    """Show/hide a pane with its ribbon toggle (e.g. View > Bookmarks). True if it changed."""
    r = _ribbon(page, label)
    if not r["toggle"]:
        t = next((t for t in r["tabs"] if t["name"] == tab), None)
        if not t:
            raise DriverError(f"Ribbon tab {tab!r} not found (an English Power BI UI is expected).")
        page.mouse.click(t["x"], t["y"])
        time.sleep(0.7)
        r = _ribbon(page, label)
        if not r["toggle"]:
            raise DriverError(f"No {label!r} button on the {tab} ribbon.")
    if r["toggle"]["pressed"] == want:
        return False
    page.mouse.click(r["toggle"]["x"], r["toggle"]["y"])
    time.sleep(0.9)
    return True


@contextmanager
def ribbon_restored(page):
    """Leave the ribbon on the tab it was on."""
    before = next((t["name"] for t in _ribbon(page)["tabs"] if t["selected"]), None)
    try:
        yield
    finally:
        if before and before != "File":
            t = next((t for t in _ribbon(page)["tabs"] if t["name"] == before and not t["selected"]), None)
            if t:
                page.mouse.click(t["x"], t["y"])
                time.sleep(0.4)


def cmd_bookmarks(a) -> dict:
    def act(s, page):
        result: dict = {}
        with ribbon_restored(page):
            opened = ensure_toggle(page, "View", "Bookmarks", True)
            try:
                items = page.evaluate(BOOKMARKS_JS) or []
                result["bookmarks"] = [i["label"] for i in items]
                if a.apply:
                    i = _match_label(result["bookmarks"], a.apply)
                    if i is None:
                        raise DriverError(f"No bookmark {a.apply!r}. Bookmarks: {result['bookmarks']}")
                    page.locator("pbi-pane.bookmarks-pane [role=treeitem].bookmark").nth(i).scroll_into_view_if_needed()
                    item = page.evaluate(BOOKMARKS_JS)[i]
                    page.mouse.click(item["x"], item["y"])
                    settle(page, a.settle)
                    result["applied"] = item["label"]
            finally:
                if opened:
                    ensure_toggle(page, "View", "Bookmarks", False)
        result["page"] = _current_page(page)
        return result
    return _interaction(a, act)


# --------------------------------------------------------------------------- performance

def _clipboard_text() -> str | None:
    import win32clipboard

    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
        except Exception:  # noqa: BLE001  another app holds it
            time.sleep(0.1)
            continue
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return None
        finally:
            win32clipboard.CloseClipboard()
    return None


def _set_clipboard_text(text: str) -> None:
    import win32clipboard

    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
            continue
        try:
            win32clipboard.EmptyClipboard()
            if text:
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return


PERF_KEYS = ("total_ms", "dax_query_ms", "visual_display_ms", "other_ms", "direct_query_ms", "parameters_ms")
PERF_HINTS = {
    "dax_query": "DAX query is the bottleneck: get the query (queries=true), time it cold with `dax --runs 3 --cold`, "
                 "and simplify the measures it uses (variables, fewer iterations over big tables, no FILTER over whole "
                 "tables) or show less detail. The Power BI Modeling MCP's dax_query_operations Execute with "
                 "GetExecutionMetrics shows storage engine vs formula engine time.",
    "direct_query": "DirectQuery is the bottleneck: the source database is slow for this query; aggregate in the source, "
                    "add an aggregation table, or switch the table to Import.",
    "visual_display": "Rendering is the bottleneck: the visual draws too many points or is complex; limit categories "
                      "(Top N filter), avoid high-cardinality axes, or use a simpler visual.",
    "other": "Waiting is the bottleneck: the visual waits for others on the page (each visual sends its own query); "
             "use fewer visuals per page, combine cards into one new card (cardVisual), or move detail to another page.",
}


def _perf_refresh(page, a, pid: int | None, cold: bool) -> list[dict]:
    """One 'Refresh visuals' in Performance Analyzer (pane open and recording); rows with the breakdown."""
    button = lambda t: page.locator(f"{PERF_PANE} button", has_text=t).first  # noqa: E731
    if button("Clear").count() and button("Clear").is_enabled():
        button("Clear").click()
        time.sleep(0.5)
    if cold:
        bridge.clear_cache(pid)
    button("Refresh visuals").click()
    time.sleep(1.5)
    settle(page, a.settle, quiet_ms=1500)
    rows: list[dict] = []
    previous, deadline = None, time.time() + a.settle
    while time.time() < deadline:  # wait until every visual has a duration and nothing changes
        rows = page.evaluate(PERF_JS) or []
        sig = [(r["name"], r["total_ms"]) for r in rows]
        if rows and sig == previous and all(r["total_ms"] is not None for r in rows):
            break
        previous = sig
        time.sleep(1)
    lifecycle = page.locator(f"{PERF_PANE} tr.visualLifecycle")
    for i in range(lifecycle.count()):
        row = lifecycle.nth(i)
        if "itemCollapsed" in (row.get_attribute("class") or ""):
            row.click()
            time.sleep(0.15)
    return page.evaluate(PERF_JS) or []


def _perf_measure(s, page, a, runs: int = 1, cold: bool = False, queries: bool = False) -> list[list[dict]]:
    """Open Performance Analyzer, refresh the visuals `runs` times (clearing the model cache first when
    `cold`), optionally copy each visual's DAX query on the last run, and close the pane again."""
    button = lambda t: page.locator(f"{PERF_PANE} button", has_text=t).first  # noqa: E731
    win = pbi_window(s.port)
    pid = win[2] if win else None
    if cold and not pid:
        raise DriverError("Couldn't find the Power BI process to clear its cache.")
    all_runs: list[list[dict]] = []
    with ribbon_restored(page):
        opened = ensure_toggle(page, "Optimize", "Performance analyzer", True)
        saved_clip = _clipboard_text() if queries else None
        try:
            if button("Start recording").count() and button("Start recording").is_enabled():
                button("Start recording").click()
                time.sleep(0.8)
            for _ in range(max(1, runs)):
                all_runs.append(_perf_refresh(page, a, pid, cold))
            if queries:
                copy_buttons = page.locator(f"{PERF_PANE} button.copyBtn")  # one per visual, in row order
                for r in all_runs[-1]:
                    if r["copy"] is None:
                        continue
                    b = copy_buttons.nth(r["copy"])
                    if not b.count() or not b.is_enabled():
                        r["query"] = None  # Power BI offers no query for this visual
                        continue
                    _set_clipboard_text("")
                    b.click()
                    for _ in range(15):  # the copy lands asynchronously
                        time.sleep(0.15)
                        r["query"] = _clipboard_text() or None
                        if r["query"]:
                            break
            if button("Stop").count() and button("Stop").is_enabled():
                button("Stop").click()
        finally:
            if queries:
                _set_clipboard_text(saved_clip or "")
            if opened:
                ensure_toggle(page, "Optimize", "Performance analyzer", False)
    return all_runs


def perf_summary(all_runs: list[list[dict]], threshold: float = 500) -> list[dict]:
    """Median timings per visual across runs (visuals keyed by name and occurrence), with the bottleneck."""
    import statistics

    keyed: dict[tuple, list[dict]] = {}
    for run in all_runs:
        seen: dict[str, int] = {}
        for r in run:
            n = seen.get(r["name"], 0)
            seen[r["name"]] = n + 1
            keyed.setdefault((r["name"], n), []).append(r)
    rows = []
    for rs in keyed.values():
        row = {k: v for k, v in rs[-1].items() if k not in ("expanded", "copy")}
        for key in PERF_KEYS:
            vals = [r[key] for r in rs if r.get(key) is not None]
            if vals:
                row[key] = round(statistics.median(vals))
        if len(all_runs) > 1:
            row["runs_ms"] = [r.get("total_ms") for r in rs]
        parts = {"dax_query": row.get("dax_query_ms") or 0, "direct_query": row.get("direct_query_ms") or 0,
                 "visual_display": row.get("visual_display_ms") or 0, "other": row.get("other_ms") or 0}
        if any(parts.values()):
            row["bottleneck"] = max(parts, key=parts.get)
        row["slow"] = (row.get("total_ms") or 0) >= threshold
        rows.append(row)
    rows.sort(key=lambda r: -(r.get("total_ms") or 0))
    return rows


def perf_hints(rows: list[dict], visual_count: int, threshold: float) -> list[str]:
    hints = []
    slow = [r for r in rows if r.get("slow")]
    for kind in PERF_HINTS:
        names = [r["name"] for r in slow if r.get("bottleneck") == kind]
        if names:
            hints.append(f"{len(names)} slow visual(s) ({', '.join(names[:5])}): {PERF_HINTS[kind]}")
    if visual_count > 15:
        hints.append(f"The page has {visual_count} visuals; pages with more than about 15 visuals load slowly because "
                     "every visual queries the model. Split the page or combine visuals.")
    if not slow:
        hints.append(f"No visual took {threshold:.0f} ms or more.")
    return hints


def _perf_page(s, page, a) -> dict:
    all_runs = _perf_measure(s, page, a, a.runs, a.cold, a.queries)
    rows = perf_summary(all_runs, a.threshold)
    data = visual_list(page, 1)
    match_perf_rows(rows, data["visuals"])
    visible = sum(1 for v in data["visuals"] if not v["hidden"])
    out = {"page": _current_page(page), "count": len(rows), "runs": len(all_runs),
           "cache": "cold" if a.cold else "warm", "threshold_ms": a.threshold,
           "slowest_ms": rows[0].get("total_ms") if rows else None,
           "sum_ms": sum(r.get("total_ms") or 0 for r in rows),
           "slow_count": sum(1 for r in rows if r.get("slow")),
           "visuals": rows[: a.top] if a.top else rows,
           "hints": perf_hints(rows, visible, a.threshold)}
    return out


def cmd_perf(a) -> dict:
    def act(s, page):
        if not a.all_pages:
            result = _perf_page(s, page, a)
            result["note"] = (f"Durations in ms from Power BI's Performance Analyzer, median of {result['runs']} "
                              f"refresh(es), {result['cache']} cache.")
            return result
        start = _current_page(page)
        pages = []
        for p in page.evaluate(PAGES_JS) or []:
            if p.get("hidden"):
                continue
            goto_page(page, p["name"], a.settle)
            r = _perf_page(s, page, a)
            r["visuals"] = r["visuals"][: a.top or 5]
            pages.append(r)
        if start:
            goto_page(page, start, a.settle)
        pages.sort(key=lambda r: -(r["slowest_ms"] or 0))
        return {"pages": pages, "count": len(pages),
                "note": f"Slowest pages first; up to {a.top or 5} slowest visuals per page. Durations in ms, "
                        f"median of {a.runs} refresh(es), {'cold' if a.cold else 'warm'} cache."}
    return _interaction(a, act)


# --------------------------------------------------------------------------- model, file, lifecycle

def cmd_dax(a) -> dict:
    if a.query == "-":
        query = sys.stdin.read()
    elif a.query:
        query = a.query
    elif a.file:
        query = Path(a.file).read_text(encoding="utf-8-sig")
    else:
        raise DriverError("Give a DAX query, --file query.dax, or - to read it from stdin.")
    pid = resolve_pid(a)
    runs = max(1, getattr(a, "runs", 1) or 1)
    cold = bool(getattr(a, "cold", False))
    batch: list[str] = []
    for _ in range(runs):
        if cold:
            batch.append(bridge.CLEAR_CACHE)
        batch.append(query)
    results = bridge.run_dax(pid, batch, a.max_rows, a.timeout)
    failed = next((r for r in results if not r.get("ok")), None)
    if failed:
        raise DriverError(("" if "ClearCache" in str(failed.get("error")) else "DAX error: ") + str(failed.get("error")))
    timed = [r for r in results if not r.get("cleared")]
    r = timed[0]
    out = {"pid": pid, **{k: r[k] for k in ("columns", "rows", "row_count", "truncated", "ms")}}
    if runs > 1 or cold:
        import statistics

        ms = [t["ms"] for t in timed]
        out["timing"] = {"runs": runs, "cache": "cold" if cold else "warm", "ms": ms, "min": min(ms),
                         "median": round(statistics.median(ms)), "max": max(ms)}
        if not cold:
            out["timing"]["note"] = "Warm runs reuse the engine cache; the first may still fill it. Add --cold to clear it before every run."
    return out


def cmd_model(a) -> dict:
    pid = resolve_pid(a)
    m = bridge.model_info(pid)
    empty = all(isinstance(v, dict) and "at least one table" in str(v.get("error")) for v in m.values())
    if empty:  # a new model: the engine refuses DAX until a table exists
        m = {k: [] for k in m}
    if a.part:
        m = {a.part: m[a.part]}
    out = {"pid": pid, "counts": {k: len(v) if isinstance(v, list) else None for k, v in m.items()}, **m}
    if empty:
        out["note"] = ("The model has no tables yet. Create them with the Power BI Modeling MCP "
                       "(table_operations Create), then refresh with `pbidriver refresh`.")
    return out


def cmd_reload(a) -> dict:
    pid = resolve_pid(a)
    t0 = time.time()
    with visible_window(pid=pid):
        r = bridge.bridge_reload(pid, model=not a.report_only)
    result: dict = {"reloaded": bool(r.get("success", True)), "pid": pid, "seconds": round(time.time() - t0, 1)}
    port = bridge.instance(pid)["devtools_port"]
    if port and _http_json(port, "/json/version"):
        with visible_window(port), pbi_session(port, wait=60) as s:
            s.report.wait_for_selector(PAGE_TAB, state="attached", timeout=60000)
            settle(s.report, a.settle)
            result["pages"] = s.report.evaluate(PAGES_JS)
            return with_alerts(result, s)
    nat = native_windows(pid=pid)
    if nat["blocked"] or nat["windows"]:
        result["alerts"] = {k: v for k, v in nat.items() if v}
    return result


def _wm_text(hwnd) -> str:
    import ctypes

    import win32con
    import win32gui

    n = win32gui.SendMessage(hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.SendMessageW(hwnd, win32con.WM_GETTEXT, n + 1, buf)
    return buf.value


def _file_dialog(hwnd) -> dict:
    """Controls of a Windows Save As dialog: file name box, type combo, Save button, current folder."""
    import win32gui

    kids = _children(hwnd)
    cls = {k: win32gui.GetClassName(k) for k in kids}
    edit = next((k for k in kids if cls[k] == "Edit" and win32gui.GetDlgCtrlID(k) == 1001), None)
    combos = [k for k in kids if cls[k] == "ComboBox" and win32gui.IsWindowVisible(k)]
    type_combo = next((c for c in combos if not any(win32gui.GetClassName(x) == "Edit" for x in _children(c))), None)
    save = next((k for k in kids if cls[k] == "Button" and win32gui.GetDlgCtrlID(k) == 1), None)
    address = next((win32gui.GetWindowText(k) for k in kids if cls[k] == "ToolbarWindow32"
                    and win32gui.GetWindowText(k).startswith("Address: ")), "")
    if not (edit and type_combo and save):
        raise DriverError("This Save As dialog doesn't have the expected controls.")
    return {"edit": edit, "type": type_combo, "save": save, "folder": address[len("Address: "):]}


def _select_file_type(combo, ext: str) -> str:
    """Pick the 'Save as type' entry for an extension. The dialog only notices a change made the way a
    dropdown makes it: open, select, notify (SELCHANGE + SELENDOK), close."""
    import ctypes

    import win32api
    import win32con
    import win32gui

    labels = []
    for i in range(win32gui.SendMessage(combo, win32con.CB_GETCOUNT, 0, 0)):
        buf = ctypes.create_unicode_buffer(win32gui.SendMessage(combo, win32con.CB_GETLBTEXTLEN, i, 0) + 1)
        ctypes.windll.user32.SendMessageW(combo, win32con.CB_GETLBTEXT, i, buf)
        labels.append(buf.value)
    index = next((i for i, label in enumerate(labels) if f"*{ext})" in label.lower()), None)
    if index is None:
        raise DriverError(f"Power BI can't save as {ext}. Types offered: {labels}")
    parent, cid = win32gui.GetParent(combo), win32gui.GetDlgCtrlID(combo)
    win32gui.SendMessage(combo, win32con.CB_SHOWDROPDOWN, 1, 0)
    win32gui.SendMessage(combo, win32con.CB_SETCURSEL, index, 0)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, win32api.MAKELONG(cid, win32con.CBN_SELCHANGE), combo)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, win32api.MAKELONG(cid, win32con.CBN_SELENDOK), combo)
    win32gui.SendMessage(combo, win32con.CB_SHOWDROPDOWN, 0, 0)
    return labels[index]


def _save_as(s: Session, a, pid: int) -> dict:
    """File > Save as > Browse this device, then drive the Windows dialog: folder, type, name, Save."""
    import win32con
    import win32gui

    target = Path(a.as_path).expanduser().resolve()
    ext = target.suffix.lower()
    if ext not in (".pbix", ".pbip", ".pbit"):
        raise DriverError("--as needs a .pbix, .pbip or .pbit path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not a.overwrite:
        raise DriverError(f"{target} already exists; pass --overwrite to replace it.")
    rp = s.report
    for label in ("File", "Save as", "Browse this device"):
        hits = rp.evaluate(FIND_JS, ["page", 0, label, True]) or []
        if not hits:
            _close_backstage(rp)
            raise DriverError(f"Couldn't find {label!r} in Power BI's File menu (an English UI is expected).")
        rp.mouse.click(hits[0]["x"], hits[0]["y"])
        time.sleep(1.5)
    dlg = None
    for _ in range(40):
        dlg = next((w for w in native_windows(pid=pid)["windows"] if w["title"] == "Save As"), None)
        if dlg:
            break
        time.sleep(0.25)
    if not dlg:
        raise DriverError("The Save As dialog didn't open.")
    hwnd = dlg["hwnd"]

    def cancel(msg: str):
        c = _file_dialog(hwnd)
        win32gui.PostMessage(next(k for k in _children(hwnd) if win32gui.GetDlgCtrlID(k) == 2
                                  and win32gui.GetClassName(k) == "Button"), win32con.BM_CLICK, 0, 0)
        raise DriverError(msg + f" (dialog folder: {c['folder']!r})")

    # 1. Go to the folder: a folder path typed as the name makes Save navigate into it.
    c = _file_dialog(hwnd)
    win32gui.SendMessage(c["edit"], win32con.WM_SETTEXT, 0, str(target.parent))
    win32gui.PostMessage(c["save"], win32con.BM_CLICK, 0, 0)
    def at_target(folder: str) -> bool:
        if "\\" in folder:
            return folder.rstrip("\\").lower() == str(target.parent).lower()
        return bool(folder) and folder.lower() == target.parent.name.lower()  # known folders show their name

    for _ in range(40):
        time.sleep(0.25)
        c = _file_dialog(hwnd)
        if at_target(c["folder"]):
            break
    else:
        cancel("The Save As dialog didn't open the target folder.")
    # 2. Type, then name (the type change rewrites the name box, so the name goes last). The dialog keeps
    #    its own copy of the name and only takes the box's text when told it was edited (CBN_EDITCHANGE).
    import win32api

    chosen = _select_file_type(c["type"], ext)
    time.sleep(0.4)
    name_combo = win32gui.GetParent(c["edit"])
    win32gui.SendMessage(c["edit"], win32con.WM_SETTEXT, 0, target.name)
    for code in (win32con.CBN_EDITUPDATE, win32con.CBN_EDITCHANGE):
        win32gui.SendMessage(win32gui.GetParent(name_combo), win32con.WM_COMMAND,
                             win32api.MAKELONG(win32gui.GetDlgCtrlID(name_combo), code), name_combo)
    time.sleep(0.3)
    if _wm_text(c["edit"]) != target.name:
        cancel("Couldn't set the file name.")
    before = (bridge.bridge_state(pid) if bridge.instance(pid)["bridge"] else {}).get("file")
    win32gui.PostMessage(c["save"], win32con.BM_CLICK, 0, 0)

    # 3. Overwrite prompt, then wait for Power BI to report the new file.
    t0 = time.time()
    while time.time() - t0 < a.timeout:
        time.sleep(1)
        wins = native_windows(pid=pid)["windows"]
        confirm = next((w for w in wins if w["title"] == "Confirm Save As"), None)
        if confirm:
            click_native_button(confirm["hwnd"], "Yes" if a.overwrite else "No")
            if not a.overwrite:
                time.sleep(0.5)
                cancel(f"{target} already exists.")
            continue
        if any(w["title"] == "Save As" for w in wins):
            continue
        state = bridge.bridge_state(pid) if bridge.instance(pid)["bridge"] else {}
        now = state.get("file")
        if now and Path(now).resolve() == target:
            return {"saved_as": str(target), "type": chosen, "seconds": round(time.time() - t0, 1),
                    "files": sorted(p.name for p in target.parent.iterdir())[:20]}
        if now and now != before:
            return {"saved_as": now, "type": chosen, "warning": f"Power BI saved to {now}, not {target}."}
        if not wins and not state:
            break
    return {"saved_as": None, "type": chosen, "note": f"Power BI didn't report {target} as the open file; check alerts."}


def _close_backstage(rp) -> None:
    hits = rp.evaluate(FIND_JS, ["page", 0, "Back", True]) or []
    if hits:
        rp.mouse.click(hits[0]["x"], hits[0]["y"])


def cmd_save(a) -> dict:
    with visible_window(a.port), pbi_session(a.port) as s:
        guard_not_blocked(s, a.force)
        win = pbi_window(a.port)
        pid = win[2] if win else None
        if a.as_path:
            if not pid:
                raise DriverError("Couldn't find the Power BI window.")
            saved_as = _save_as(s, a, pid)
            return with_alerts(with_caution(saved_as, saved_as.get("file") or a.as_path), s)
        has_bridge = bool(pid and bridge.instance(pid)["bridge"])
        before = bridge.bridge_state(pid)["unsaved"] if has_bridge else None
        # Ctrl+S is a host accelerator that DevTools key events never reach; the title bar's Save
        # button is part of the page, so click that.
        btn = s.report.evaluate("""() => { const b = [...document.querySelectorAll('button[aria-label="Save"]')]
            .find(b => !b.disabled && b.getBoundingClientRect().width > 2);
            if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }""")
        if not btn:
            raise DriverError("Power BI's Save button was not found (or is disabled).")
        s.report.mouse.click(btn["x"], btn["y"])
        saved, t0 = None, time.time()
        while time.time() - t0 < a.timeout:
            time.sleep(1)
            alerts = collect_alerts(s, visual_errors=False)
            if alerts.get("blocked") or alerts.get("dialogs"):
                break
            if has_bridge and not bridge.bridge_state(pid)["unsaved"]:
                saved = True
                break
            if not has_bridge and time.time() - t0 > 5:
                break
        result = {"saved": saved, "had_unsaved_changes": before, "file": report_file(a.port),
                  "seconds": round(time.time() - t0, 1)}
        with_caution(result, result["file"])
        if saved is None:
            result["note"] = ("Save is still running or waiting for a dialog; check `alerts`." if has_bridge
                              else "No Desktop Bridge on this build, so the save could not be confirmed.")
        return with_alerts(result, s)


EMPTY_TABLES_BANNER = "incomplete or no data"


def _sync_model(a) -> dict:
    """Save, then reload the whole PBIP from disk: Power BI's own refresh only knows the queries it has read
    from the project, so tables added through the Modeling MCP (TOM) are skipped until it re-reads them."""
    pid = resolve_pid(a)
    file = (bridge.bridge_state(pid).get("file") or "") if bridge.instance(pid)["bridge"] else ""
    if not file.lower().endswith(".pbip"):
        raise DriverError("--sync needs a PBIP project open (it saves and reloads it). Convert with "
                          "`pbidriver save --as <file.pbip>`.")
    saved = cmd_save(argparse.Namespace(**{**vars(a), "as_path": None, "overwrite": False, "timeout": 120}))
    reloaded = cmd_reload(argparse.Namespace(**{**vars(a), "report_only": False}))
    return {"saved": bool(saved.get("saved")), "reloaded": bool(reloaded.get("reloaded"))}


def cmd_refresh(a) -> dict:
    """Home > Refresh: reload every table's data, then wait until Power BI's refresh dialog is gone."""
    synced = _sync_model(a) if getattr(a, "sync", False) else None
    with visible_window(a.port), pbi_session(a.port) as s:
        guard_not_blocked(s, a.force)
        rp = s.report
        with ribbon_restored(rp):
            tab = next((t for t in _ribbon(rp)["tabs"] if t["name"] == "Home"), None)
            if tab and not tab["selected"]:
                rp.mouse.click(tab["x"], tab["y"])
                time.sleep(0.6)
            btn = rp.evaluate("""() => { const b = [...document.querySelectorAll('button[aria-label="Refresh"]')]
                .map(e => e.getBoundingClientRect()).find(r => r.width > 0 && r.top < 200);
                return b ? {x: b.left + b.width / 2, y: b.top + b.height / 2} : null; }""")
            if not btn:
                raise DriverError("Couldn't find the Refresh button on the Home ribbon.")
            rp.mouse.click(btn["x"], btn["y"])
            t0, quiet = time.time(), 0
            seen_progress = False
            error_re = re.compile(r"error|couldn't|could not|failed|blocked", re.I)
            while time.time() - t0 < a.timeout:
                time.sleep(1)
                alerts = collect_alerts(s, visual_errors=False)
                dialogs = alerts.get("dialogs", [])
                errors = [d for d in dialogs if error_re.search(d.get("text") or "")]
                if errors:
                    return with_alerts({"refreshed": False, "seconds": round(time.time() - t0, 1),
                                        "error": errors[0]["text"][:600],
                                        "next": "Fix the source, then `pbidriver dialog --click Close` and retry."}, s)
                busy = bool(alerts.get("blocked")) or any(re.search(r"refresh|load", d.get("text") or "", re.I)
                                                          for d in dialogs)
                seen_progress = seen_progress or busy
                quiet = 0 if busy else quiet + 1
                if quiet >= 3 and (seen_progress or time.time() - t0 > 6):
                    break
            else:
                return with_alerts({"refreshed": False, "seconds": round(time.time() - t0, 1),
                                    "error": f"Still refreshing after {a.timeout}s."}, s)
        settle(rp, a.settle)
        result: dict = {"refreshed": True, "seconds": round(time.time() - t0, 1)}
        banners = collect_alerts(s, visual_errors=False).get("banners", [])
        if any(EMPTY_TABLES_BANNER in b["text"] for b in banners):
            result.update(refreshed=False, error="Power BI's refresh finished but some tables are still empty. "
                          "Tables created or changed through the Power BI Modeling MCP are only part of Power BI's "
                          "own refresh after it re-reads the model.",
                          next="pbidriver refresh --sync  (saves, reloads the project from disk, refreshes, saves)")
        result = with_alerts(result, s)
    if synced:
        # Save now: a report reload (add-visual --reload, reload --report-only) makes Power BI forget that the
        # data changed, and a later save would then keep the old (empty) data cache.
        if result["refreshed"]:
            synced["saved_after"] = bool(cmd_save(argparse.Namespace(
                **{**vars(a), "as_path": None, "overwrite": False, "timeout": 120})).get("saved"))
        result["synced"] = synced
    elif result["refreshed"] and (report_file(a.port) or "").lower().endswith(".pbip"):
        result["next"] = ("pbidriver save, before any report reload: a reload makes Power BI forget the data "
                          "changed, and the project would keep its old data.")
    return result


# --------------------------------------------------------------------------- project authoring (PBIR)

def _project_report(a):
    """The PBIR report folder to edit: --project, else the .pbip open in Power BI."""
    from pbidriver import project

    if getattr(a, "project", None):
        return project.report_dir(a.project)
    try:
        pid = resolve_pid(a)
        info = bridge.instance(pid)
        file = (bridge.bridge_state(pid)["file"] if info["bridge"] else None) or info["file"]
    except (DriverError, bridge.BridgeError):
        file = None
    if not file or not file.lower().endswith(".pbip"):
        raise DriverError("No PBIP project is open in Power BI. Pass --project <file.pbip>, open one with "
                          "`pbidriver launch`, or convert a .pbix with `pbidriver save --as <file.pbip>`.")
    return project.report_dir(file)


def _model_fields(a, rep) -> tuple[dict, str]:
    """Tables, columns and measures to check field names against: the live model if Power BI has this
    project open (includes unsaved changes, e.g. from the Modeling MCP), else the TMDL files."""
    from pbidriver import project

    try:
        pid = resolve_pid(a)
        info = bridge.instance(pid)
        file = (bridge.bridge_state(pid)["file"] if info["bridge"] else None) or info["file"] or ""
        if info["model_port"] and file.lower().endswith(".pbip") and project.report_dir(file) == rep:
            return project.model_fields_from_info(bridge.model_info(pid)), "live model"
    except (DriverError, bridge.BridgeError, project.ProjectError):
        pass
    sem = project.model_dir(rep)
    if sem and (sem / "definition").is_dir():
        return project.model_fields_from_tmdl(sem / "definition"), "TMDL files"
    return {}, "none"


def _after_edit(a, result: dict, page_name: str | None) -> dict:
    """--reload / --shot: have Power BI pick up the edited files, then capture the page."""
    with_caution(result, result.get("file") or result.get("report"))
    if not (getattr(a, "reload", False) or getattr(a, "shot", False)):
        result["next"] = "Run `pbidriver reload --report-only` to see the change in Power BI."
        return result
    pid = resolve_pid(a)
    with visible_window(pid=pid):
        bridge.bridge_reload(pid, model=False)
    result["reloaded"] = True
    port = bridge.instance(pid)["devtools_port"]
    if getattr(a, "shot", False):
        if port and _http_json(port, "/json/version"):
            with visible_window(port), pbi_session(port, wait=60) as s:
                s.report.wait_for_selector(PAGE_TAB, state="attached", timeout=60000)
                settle(s.report, a.settle)
                page = goto_page(s.report, page_name, a.settle)
                s.report.mouse.move(1, 1)
                settle(s.report, a.settle, quiet_ms=400)
                out = getattr(a, "out", None)
                path = as_png(Path(out).expanduser().resolve() if out else default_out(page["name"]))
                clean = bool(getattr(a, "clean", False))
                with fit_canvas(s.report, s.cdp(s.report), a.settle):
                    shot = canvas_capture(s, s.report, a, page["name"], path, [] if clean else ["index", "type"], clean)
                result["legend"] = shot.pop("legend", None)
                if "layout" in shot:
                    result["layout"] = shot.pop("layout")
                result["shot"] = {k: shot[k] for k in ("file", "size")}
                return with_alerts(result, s)
        a.page, a.visual, a.all_visuals, a.full, a.bridge, a.view, a.scale = page_name, None, False, False, True, "report", 1
        a.out = getattr(a, "out", None)
        result["shot"] = cmd_shot_bridge(a)
    return result


def cmd_new(a) -> dict:
    from pbidriver import project

    if a.open and _http_json(a.port, "/json/version"):  # check before writing anything, so a retry can succeed
        raise DriverError(f"Port {a.port} already has a Power BI window with DevTools. Pass another --port "
                          "(each window needs its own), or close that one first.")
    out = project.new_project(a.folder, a.name, page=a.page_name, width=a.width, height=a.height)
    if a.git:
        from pbidriver import kit

        out["git"] = kit.git_init(Path(out["pbip"]).parent, f"New Power BI project {a.name} (pbidriver new)")
    else:
        with_caution(out, out["pbip"])
    if a.open:
        a.file = out["pbip"]
        out["launch"] = cmd_launch(a)
        inst = next((i for i in bridge.instances() if i.get("devtools_port") == a.port), {})
        if inst.get("model_port"):
            out["model_port"] = inst["model_port"]
            out["next"] = (f"Build the model with the Power BI Modeling MCP: connection_operations Connect with "
                           f"dataSource localhost:{inst['model_port']}; then `pbidriver refresh --sync` and add "
                           f"visuals with `pbidriver add-visual`.")
    else:
        out["next"] = f'pbidriver launch "{out["pbip"]}"'
    return out


def cmd_layout(a) -> dict:
    from pbidriver import project

    rep = _project_report(a)
    pages = project.list_pages(rep)
    if a.page is not None or len(pages) == 1:
        page = project.find_page(rep, a.page)
        return {"report": str(rep), "page": page, "visuals": project.list_visuals(rep, page["id"])}
    return {"report": str(rep), "pages": pages}


def cmd_add_page(a) -> dict:
    from pbidriver import project

    rep = _project_report(a)
    page = project.add_page(rep, a.name, a.width, a.height)
    return _after_edit(a, {"report": str(rep), "added_page": page}, page["name"])


def cmd_add_visual(a) -> dict:
    from pbidriver import project

    rep = _project_report(a)
    fields, source = _model_fields(a, rep)
    spec = project.VISUALS.get(a.type)
    if spec is None:
        raise DriverError(f"Unsupported visual type {a.type!r}. Supported: {', '.join(project.VISUALS)}")
    roles: dict[str, list[str]] = {}
    for item in a.field or []:
        role, sep, value = item.partition("=")
        if sep and role.strip() in {r for r, _ in spec["roles"]}:
            roles.setdefault(role.strip(), []).append(value.strip())
            continue
        # No role given: the first empty role that takes this kind of field, else the last one that does.
        kind = project.parse_field(item, fields)["kind"]
        kind = "measure" if kind == "aggregate" else kind
        fitting = [r for r, k in spec["roles"] if k in (kind, "any")]
        if not fitting:
            raise DriverError(f"{a.type} has no role for {item!r}. Roles: {[r for r, _ in spec['roles']]}")
        role = next((r for r in fitting if r not in roles), fitting[-1])
        roles.setdefault(role, []).append(item)
    page = project.find_page(rep, a.page)
    w = a.width or (page["width"] or 1280) // 3
    h = a.height or (page["height"] or 720) // 3
    out = project.add_visual(rep, page["id"], a.type, roles, a.x, a.y, w, h, title=a.title, text=a.text,
                             slicer_mode=a.mode, fields=fields or None, sort=a.sort, sort_dir=a.sort_dir)
    out["fields_checked_against"] = source
    return _after_edit(a, out, page["name"])


def cmd_remove_visual(a) -> dict:
    from pbidriver import project

    rep = _project_report(a)
    out = project.remove_visual(rep, a.page, a.id)
    out.setdefault("report", str(rep))
    return _after_edit(a, out, out["page"])


def _web_dialog(port: int | None) -> dict | None:
    """The topmost in-app (WebView2) dialog of a DevTools instance, if any."""
    if not port or not _http_json(port, "/json/version"):
        return None
    try:
        with pbi_session(port, wait=2) as s:
            for key, page in s.floating_pages().items():
                found = page.evaluate(FLOATING_JS)
                if found["text"]:
                    return {"kind": "in-app", "view": f"floating:{key}", **found}
            for name in ("dialoghost", "report"):
                page = s.pages.get(DIALOG_HOST if name == "dialoghost" else VIEWS[name])
                found = page.evaluate(WEB_ALERTS_JS)["dialogs"] if page else []
                if found:
                    return {"kind": "in-app", "view": name, **found[-1]}
    except Exception:  # noqa: BLE001  the app may be shutting down
        return None
    return None


def _press_web_dialog(port: int, view: str, label: str) -> str:
    with pbi_session(port, wait=2) as s:
        if view.startswith("floating:"):
            page, scope = s.floating_pages().get(view.split(":", 1)[1]), "page"
        else:
            page, scope = s.pages.get(DIALOG_HOST if view == "dialoghost" else VIEWS[view]), "dialog"
        if page is None:
            raise DriverError("The dialog is gone.")
        hits = [h for h in (page.evaluate(FIND_JS, [scope, 0, label, False]) or [])
                if h["tag"] in ("button", "input", "a", "span", "div") or h["role"] == "button"]
        if not hits:
            raise DriverError(f"No button {label!r} in the dialog.")
        page.mouse.click(hits[0]["x"], hits[0]["y"])
        return hits[0]["label"]


def cmd_close(a) -> dict:
    import psutil
    import win32con
    import win32gui

    pid = resolve_pid(a)
    win = bridge.main_window(pid)
    if not win:
        raise DriverError(f"No Power BI window for process {pid}.")
    port = bridge.instance(pid)["devtools_port"]
    want = "Don't save" if a.discard else ("Save" if a.save else None)
    if win32gui.IsWindowEnabled(win[0]):  # disabled = a prompt (e.g. from an earlier close) is already up
        win32gui.PostMessage(win[0], win32con.WM_CLOSE, 0, 0)
    answered: list[str] = []
    dismissed: list[str] = []
    t0 = time.time()
    while time.time() - t0 < a.timeout:
        time.sleep(1)
        if not psutil.pid_exists(pid):
            return {"closed": True, "pid": pid, "answered": answered[-1] if answered else None,
                    "dismissed": dismissed or None, "seconds": round(time.time() - t0, 1)}
        nat = native_windows(pid=pid)
        prompt = next((w for w in nat["windows"] if w["kind"] in ("native", "legacy-ie") and w["buttons"]), None)
        web = None if prompt else _web_dialog(port)
        if prompt is None and web is None:
            if not nat["blocked"] and win32gui.IsWindow(win[0]) and win32gui.IsWindowEnabled(win[0]) and (answered or dismissed):
                win32gui.PostMessage(win[0], win32con.WM_CLOSE, 0, 0)  # a dismissed error dialog cancelled the close
                dismissed.append("(asked to close again)")
            continue
        shown = web or prompt
        buttons = shown.get("buttons") or []
        is_save_prompt = any(_match_label([b], "Don't save") is not None for b in buttons)
        if not want:
            return {"closed": False, "pid": pid, "prompt": shown,
                    "hint": "Power BI asks before closing. Run `close --discard` or `close --save`, or `dialog --click <button>`."}
        label = want if is_save_prompt else next((b for b in ("Close", "OK", "Cancel") if _match_label(buttons, b) is not None), None)
        if label is None:
            return {"closed": False, "pid": pid, "prompt": shown, "hint": "Answer this dialog with `dialog --click <button>`."}
        if web:
            pressed = _press_web_dialog(port, web["view"], label)
        else:
            pressed = click_native_button(prompt["hwnd"], label)
        (answered if is_save_prompt else dismissed).append(pressed)
    return {"closed": not psutil.pid_exists(pid), "pid": pid, "answered": answered[-1] if answered else None,
            "dismissed": dismissed or None, "note": f"Still running after {a.timeout:.0f}s."}


def cmd_wait(a) -> dict:
    with visible_window(a.port), pbi_session(a.port) as s:
        page = s.view(a.view)
        want, t0 = _norm(a.text), time.time()
        while True:
            present = want in _norm(page.evaluate("() => document.body.innerText || ''"))
            if present != a.gone:
                if not a.gone:
                    settle(page, a.settle, quiet_ms=400)
                return with_alerts({"text": a.text, "present": present, "seconds": round(time.time() - t0, 1)}, s, (a.view,))
            if time.time() - t0 > a.timeout:
                raise DriverError(f"Timed out after {a.timeout:.0f}s waiting for {a.text!r} to {'disappear' if a.gone else 'appear'}.")
            time.sleep(0.5)


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"DevTools port (default {DEFAULT_PORT}, env PBIDRIVER_PORT)")
    common.add_argument("--settle", type=float, default=float(os.environ.get("PBIDRIVER_SETTLE", "20")),
                        help="max seconds to wait for rendering to finish (default 20, env PBIDRIVER_SETTLE); "
                             "lower it for faster commands on light pages")
    common.add_argument("--pid", type=int, help="Power BI process id (see `instances`); for Bridge and model commands")

    report_inter = argparse.ArgumentParser(add_help=False)
    report_inter.add_argument("--page", help="report page name or index to switch to first")
    report_inter.add_argument("--shot", action="store_true", help="capture the canvas after the action")
    report_inter.add_argument("--force", action="store_true", help="act even while a modal dialog blocks Power BI")

    inter = argparse.ArgumentParser(add_help=False)
    inter.add_argument("--view", choices=list(VIEWS), default="report", help="which Power BI view to act in (default report)")
    inter.add_argument("--page", help="report page name or index to switch to first")
    inter.add_argument("--shot", action="store_true", help="capture the canvas/view after the action")
    inter.add_argument("--force", action="store_true", help="act even while a modal dialog blocks Power BI")

    target = argparse.ArgumentParser(add_help=False)
    target.add_argument("--visual", help="report visual index or text match")
    target.add_argument("--text", help="element to aim at, matched by aria-label or text (inside --visual if given)")
    target.add_argument("--exact", action="store_true", help="--text must match exactly")
    target.add_argument("--at", help="X,Y: fractions (0-1) or px inside --visual, else page px")

    p = argparse.ArgumentParser(prog="pbidriver", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("launch", parents=[common], help="open a report in an isolated Power BI instance with DevTools enabled")
    s.add_argument("file", help=".pbix, .pbip or .pbit to open")
    s.add_argument("--timeout", type=float, default=300, help="max seconds to wait for the report to load (default 300)")
    s.set_defaults(func=cmd_launch)

    s = sub.add_parser("instances", parents=[common], help="every running Power BI Desktop: pid, file, DevTools, Bridge")
    s.set_defaults(func=cmd_instances)

    s = sub.add_parser("status", parents=[common], help="instance state, current page, unsaved changes, alerts")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("pages", parents=[common], help="list report pages")
    s.set_defaults(func=cmd_pages)

    s = sub.add_parser("alerts", parents=[common], help="dialogs, banners and broken visuals right now")
    s.add_argument("--all-views", action="store_true", help="also scan the Table/Model/DAX/TMDL views")
    s.set_defaults(func=cmd_alerts)

    s = sub.add_parser("visuals", parents=[common], help="live list of visuals: type, label, box, text, error")
    s.add_argument("--page", help="page name or index (default: current page)")
    s.add_argument("--all-pages", action="store_true", help="walk every page (restores the current one)")
    s.add_argument("--text-limit", type=int, default=300, help="max characters of text per visual, 0 = all (default 300)")
    s.set_defaults(func=cmd_visuals)

    s = sub.add_parser("inventory", parents=[common], help="all pages/visuals/fields from the report file, no clicking")
    s.add_argument("--file", help=".pbix/.pbip/.pbit (default: the file the instance was launched with)")
    s.add_argument("--type", help="only visuals whose type contains this text")
    s.add_argument("--summary", action="store_true", help="only the per-type summary")
    s.set_defaults(func=cmd_inventory)

    s = sub.add_parser("shot", parents=[common], help="capture the canvas, a visual, every visual, the full UI, or another view")
    s.add_argument("--view", choices=list(VIEWS), default="report", help="report (default) or table/model/dax/tmdl")
    s.add_argument("--page", help="page name or index (default: current page)")
    what = s.add_mutually_exclusive_group()
    what.add_argument("--visual", help="visual index (from `visuals`) or text to match against its label/type/text")
    what.add_argument("--all-visuals", action="store_true", help="save every visible visual as its own PNG")
    what.add_argument("--full", action="store_true", help="capture the whole Power BI UI instead of only the canvas")
    s.add_argument("--scale", type=float, default=1, help="resolution multiplier, e.g. 2 (default 1)")
    s.add_argument("--out", help="output .png path (or folder with --all-visuals). Default: ./pbidriver_shots/<time>_<name>")
    s.add_argument("--annotate", action="store_true", help="draw each visual's index and type on the canvas capture "
                                                           "(same as --overlay index type)")
    s.add_argument("--overlay", nargs="+", metavar="ITEM",
                   choices=["index", "type", "title", "size", "pos", "errors", "perf", "grid", "align", "gaps",
                            "overlap", "all"],
                   help="what to draw on the canvas capture: index, type, title, size, pos (page units), errors, "
                        "perf (render ms, runs Performance Analyzer), grid, align (near-miss edges), gaps (spacing), "
                        "overlap, or all (everything but perf)")
    s.add_argument("--clean", action="store_true",
                   help="for judging the design: no overlays, no selection, hover or open menus; still returns the "
                        "legend and a layout check (overlaps, near-misses, uneven gaps)")
    s.add_argument("--grid-size", type=int, default=40, help="grid spacing in page units for --overlay grid (default 40)")
    s.add_argument("--threshold", type=float, default=500,
                   help="ms from which --overlay perf marks a visual red (default 500)")
    s.add_argument("--bridge", action="store_true", help="capture through the Desktop Bridge (automatic when there is no DevTools)")
    s.set_defaults(func=cmd_shot)

    s = sub.add_parser("read", parents=[common, report_inter], help="data behind visuals: chart points, cards, tables, slicers")
    s.add_argument("--visual", help="one visual (index or text match); default: every visual on the page")
    s.add_argument("--max-rows", type=int, help="max rows per visual (default 200 for one visual, 50 for a whole page)")
    s.set_defaults(func=cmd_read, view="report")

    s = sub.add_parser("dax", parents=[common], help="run a DAX query against the open model")
    s.add_argument("query", nargs="?", help='DAX, e.g. "EVALUATE TOPN(10, Sales)"; - reads stdin')
    s.add_argument("--file", help="read the query from a .dax file")
    s.add_argument("--max-rows", type=int, default=1000, help="max rows returned (default 1000)")
    s.add_argument("--timeout", type=int, default=120, help="query timeout in seconds (default 120)")
    s.add_argument("--runs", type=int, default=1, help="run the query N times and report the timings (min/median/max)")
    s.add_argument("--cold", action="store_true", help="clear the model engine's cache before each run (cold timings)")
    s.set_defaults(func=cmd_dax)

    s = sub.add_parser("model", parents=[common], help="tables, columns, measures (with DAX) and relationships")
    s.add_argument("--part", choices=["tables", "columns", "measures", "relationships"], help="only this part")
    s.set_defaults(func=cmd_model)

    s = sub.add_parser("perf", parents=[common, report_inter], help="Performance Analyzer: per-visual render and query times")
    s.add_argument("--queries", action="store_true", help="also return each visual's DAX query (uses the clipboard, then restores its text)")
    s.add_argument("--runs", type=int, default=1, help="refresh the visuals N times and report medians (default 1)")
    s.add_argument("--cold", action="store_true", help="clear the model engine's cache before each refresh (cold timings)")
    s.add_argument("--threshold", type=float, default=500, help="ms from which a visual counts as slow (default 500)")
    s.add_argument("--top", type=int, help="only the N slowest visuals")
    s.add_argument("--all-pages", action="store_true", help="measure every visible page, slowest pages first")
    s.set_defaults(func=cmd_perf, view="report")

    s = sub.add_parser("bookmarks", parents=[common, report_inter], help="list bookmarks, or apply one")
    s.add_argument("--apply", help="bookmark name to apply")
    s.set_defaults(func=cmd_bookmarks, view="report")

    s = sub.add_parser("reload", parents=[common], help="reload a PBIP/PBIR report from disk (Desktop Bridge)")
    s.add_argument("--report-only", action="store_true", help="reload only the report, not the semantic model definition")
    s.set_defaults(func=cmd_reload)

    s = sub.add_parser("save", parents=[common], help="save the report (confirmed through the Desktop Bridge), or --as a new file")
    s.add_argument("--as", dest="as_path", help="save a copy as this .pbip (PBIP project), .pbix or .pbit and switch to it")
    s.add_argument("--overwrite", action="store_true", help="with --as: replace an existing file")
    s.add_argument("--force", action="store_true", help="act even while a modal dialog blocks Power BI")
    s.add_argument("--timeout", type=float, default=120, help="max seconds to wait for the save (default 120)")
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("refresh", parents=[common], help="refresh all data (Home > Refresh) and wait for it")
    s.add_argument("--sync", action="store_true",
                   help="save the PBIP and reload it from disk first, so tables created or changed through the "
                        "Power BI Modeling MCP are refreshed too, and save again afterwards (use after model changes)")
    s.add_argument("--force", action="store_true", help="act even while a modal dialog blocks Power BI")
    s.add_argument("--timeout", type=float, default=600, help="max seconds to wait (default 600)")
    s.set_defaults(func=cmd_refresh)

    proj = argparse.ArgumentParser(add_help=False)
    proj.add_argument("--project", help=".pbip file or project folder (default: the PBIP open in Power BI)")
    after = argparse.ArgumentParser(add_help=False)
    after.add_argument("--reload", action="store_true",
                       help="show the change in Power BI: a report-only reload, which keeps unsaved model changes")
    after.add_argument("--shot", action="store_true",
                       help="reload (report only), then capture the page with visual indices drawn on it")
    after.add_argument("--out", help="with --shot: output .png path (default ./pbidriver_shots/<time>_<page>.png)")
    after.add_argument("--clean", action="store_true",
                       help="with --shot: no overlay, for judging how the page looks (adds a layout check instead)")

    s = sub.add_parser("new", parents=[common], help="create a blank PBIP project (PBIR report + TMDL model)")
    s.add_argument("folder", help="folder to create the project in")
    s.add_argument("--name", required=True, help="project name, e.g. Sales")
    s.add_argument("--page-name", default="Page 1", help="name of the first page")
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720)
    s.add_argument("--open", action="store_true", help="open it with `launch` right away")
    s.add_argument("--git", action="store_true", help="put the project under git: `git init` and a first commit")
    s.add_argument("--timeout", type=float, default=300, help="with --open: max seconds to wait for Power BI")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("layout", parents=[common, proj], help="pages and visuals in the PBIR files (ids, types, positions, fields)")
    s.add_argument("--page", help="page name, index or id")
    s.set_defaults(func=cmd_layout)

    s = sub.add_parser("add-page", parents=[common, proj, after], help="add a report page to the PBIR files")
    s.add_argument("name", help="page display name")
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720)
    s.set_defaults(func=cmd_add_page)

    s = sub.add_parser("add-visual", parents=[common, proj, after], help="add a visual to a page in the PBIR files")
    from pbidriver.project import VISUALS

    s.add_argument("type", choices=list(VISUALS), metavar="TYPE",
                   help="visual type: " + ", ".join(VISUALS) + " (tableEx = table, pivotTable = matrix)")
    s.add_argument("--field", action="append", help='ROLE=FIELD or just FIELD, e.g. Category=Sales[Region] or "[Total Sales]" '
                                                    "or Sum(Sales[Amount]); repeat for more")
    s.add_argument("--page", help="page name, index or id (default: the active page)")
    s.add_argument("--x", type=float, default=20)
    s.add_argument("--y", type=float, default=20)
    s.add_argument("--width", type=float, help="default: a third of the page")
    s.add_argument("--height", type=float, help="default: a third of the page")
    s.add_argument("--title", help="visual title")
    s.add_argument("--text", help="textbox text (\\n for new lines)")
    s.add_argument("--mode", choices=["dropdown", "list"], help="slicer style")
    s.add_argument("--sort", help='field to sort by, usually one of the visual\'s, e.g. "[Total Revenue]"')
    s.add_argument("--sort-dir", choices=["desc", "asc"], default="desc", help="sort direction (default desc)")
    s.set_defaults(func=cmd_add_visual)

    s = sub.add_parser("remove-visual", parents=[common, proj, after], help="delete a visual from the PBIR files")
    s.add_argument("id", help="visual id (from `layout`)")
    s.add_argument("--page", help="page name, index or id")
    s.set_defaults(func=cmd_remove_visual)

    s = sub.add_parser("close", parents=[common], help="close a Power BI window; answers the save prompt if told how")
    how = s.add_mutually_exclusive_group()
    how.add_argument("--discard", action="store_true", help="answer the save prompt with Don't save")
    how.add_argument("--save", action="store_true", help="answer the save prompt with Save")
    s.add_argument("--timeout", type=float, default=60, help="max seconds to wait for the process to exit (default 60)")
    s.set_defaults(func=cmd_close)

    s = sub.add_parser("wait", parents=[common], help="wait until text appears (or disappears with --gone)")
    s.add_argument("--text", required=True)
    s.add_argument("--gone", action="store_true")
    s.add_argument("--view", choices=list(VIEWS), default="report")
    s.add_argument("--timeout", type=float, default=30)
    s.set_defaults(func=cmd_wait)

    s = sub.add_parser("dialog", parents=[common], help="read, answer (--click) or capture (--shot) the blocking dialog")
    s.add_argument("--click", help="button to press, e.g. Cancel")
    s.add_argument("--shot", action="store_true", help="capture the dialog")
    s.add_argument("--out", help="output .png path for --shot")
    s.add_argument("--view", choices=list(VIEWS), default="report", help="view whose in-app dialogs to consider")
    s.set_defaults(func=cmd_dialog)

    s = sub.add_parser("click", parents=[common, inter, target], help="click an element (in a visual, a view, or at a point)")
    s.add_argument("--ctrl", action="store_true")
    s.add_argument("--shift", action="store_true")
    s.add_argument("--alt", action="store_true")
    s.add_argument("--double", action="store_true")
    s.add_argument("--right", action="store_true")
    s.set_defaults(func=cmd_click)

    s = sub.add_parser("hover", parents=[common, inter, target], help="hover a point and read the tooltip")
    s.set_defaults(func=cmd_hover)

    s = sub.add_parser("menu", parents=[common, inter, target], help="open a context menu (or --more) and list / --choose items")
    s.add_argument("--more", action="store_true", help="the visual's 'More options' menu instead of a right-click")
    s.add_argument("--choose", help='item to click; submenus with ">", e.g. "Sort axis > Sort descending"')
    s.set_defaults(func=cmd_menu)

    s = sub.add_parser("scroll", parents=[common, inter, target], help="mouse-wheel scroll over a visual, the canvas or a grid")
    s.add_argument("--dx", type=float, default=0, help="horizontal wheel delta in px (positive = right)")
    s.add_argument("--dy", type=float, default=0, help="vertical wheel delta in px (positive = down)")
    s.set_defaults(func=cmd_scroll)

    s = sub.add_parser("type", parents=[common, inter], help="type text (optionally clicking an input first)")
    s.add_argument("value", help="text to type")
    s.add_argument("--visual", help="visual to click into first (e.g. a search slicer)")
    s.add_argument("--into", help="element to click first, by aria-label/text (inside --visual if given)")
    s.add_argument("--exact", action="store_true")
    s.add_argument("--press", help="key to press after typing, e.g. Enter")
    s.set_defaults(func=cmd_type, at=None)

    s = sub.add_parser("key", parents=[common, inter], help="press keys, e.g. Escape, Control+A, PageDown")
    s.add_argument("keys", nargs="+")
    s.set_defaults(func=cmd_key)

    s = sub.add_parser("slicer", parents=[common, inter], help="read or set a slicer's selection (list or dropdown)")
    s.add_argument("--visual", required=True, help="slicer visual index or text match")
    act = s.add_mutually_exclusive_group()
    act.add_argument("--select", nargs="+", help="values to select (exactly these)")
    act.add_argument("--clear", action="store_true", help="clear the selection")
    s.set_defaults(func=cmd_slicer)

    s = sub.add_parser("guide", help="the powerbi-builder guide for agents: workflow, visuals, modeling-mcp, pbir, troubleshooting")
    s.add_argument("topic", nargs="?", default="workflow",
                   choices=["workflow", "visuals", "design", "performance", "modeling-mcp", "pbir", "troubleshooting"])
    s.set_defaults(func=cmd_guide)

    s = sub.add_parser("locate", help="where pbidriver and the Power BI Modeling MCP (VS Code extension) are, and how to install them")
    s.set_defaults(func=cmd_locate)

    s = sub.add_parser("bug-report", help="draft a GitHub issue for a pbidriver bug (redacted; nothing is sent)")
    s.add_argument("--command", dest="bug_command", help="the pbidriver command or MCP tool call that failed")
    s.add_argument("--error", help="the error or wrong result (e.g. the JSON pbidriver returned)")
    s.add_argument("--expected", help="what should have happened")
    s.add_argument("--details", help="anything else: steps, how often, what you tried")
    s.add_argument("--title", help="issue title (default: from the command and error)")
    s.add_argument("--out", help="where to write the draft .md (default: a temp folder)")
    s.set_defaults(func=cmd_bug_report)

    s = sub.add_parser("doctor", parents=[common], help="check Power BI, the Desktop Bridge, the Modeling MCP and project setup")
    s.add_argument("--project", help="project folder whose agent setup to check (default: current folder)")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("setup", help="set up a project for agents: MCP configs, AGENTS.md, the powerbi-builder skill")
    s.add_argument("folder", nargs="?", default=".", help="project folder (default: current folder)")
    s.add_argument("--client", action="append", choices=["claude", "vscode", "cursor", "codex", "all"],
                   help="agent(s) to configure; repeat for more (default: claude, vscode, cursor)")
    s.add_argument("--runner", choices=["auto", "uvx", "npx", "python"], default="auto",
                   help="how clients start the pbidriver MCP server (default: uvx if installed, else npx, else this Python)")
    s.add_argument("--modeling", choices=["auto", "npx", "exe", "none"], default="auto",
                   help="how clients start the Power BI Modeling MCP (default: npx if Node is installed, "
                        "else the VS Code extension's exe)")
    s.add_argument("--force", action="store_true", help="replace existing pbidriver / Modeling MCP entries")
    s.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("mcp", help="run as an MCP server over stdio (Claude Code, VS Code, Cursor, Codex, ...)",
                       description="Run pbidriver as an MCP server over stdio. Options: --no-images, --cwd DIR.")
    s.set_defaults(func=cmd_mcp)  # main() hands `mcp` to the server before parsing; this is for completeness
    return p


def cmd_mcp(a) -> dict:
    from pbidriver import mcp_server

    raise SystemExit(mcp_server.main([]))


def cmd_guide(a) -> dict:
    from pbidriver import mcp_server

    path = Path(__file__).with_name("skill") / "powerbi-builder" / mcp_server.GUIDE_TOPICS[a.topic]
    return {"topic": a.topic, "file": str(path), "topics": list(mcp_server.GUIDE_TOPICS),
            "text": mcp_server._guide(a.topic)}


def cmd_locate(a) -> dict:
    from pbidriver import kit

    return kit.locate()


def cmd_bug_report(a) -> dict:
    from pbidriver import kit

    return kit.bug_report(a.bug_command, a.error, a.expected, a.title, a.details, a.out)


def with_caution(result: dict, path) -> dict:
    """Add a `caution` to results of commands that change project files outside version control."""
    from pbidriver import kit

    note = kit.vcs_caution(path)
    if note:
        result["caution"] = note
    return result


def cmd_doctor(a) -> dict:
    from pbidriver import kit

    return kit.doctor(a.project)


def cmd_setup(a) -> dict:
    from pbidriver import kit

    try:
        return kit.setup(a.folder, a.client, a.runner, a.modeling, a.force, a.dry_run)
    except ValueError as e:
        raise DriverError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["mcp"]:  # the server owns stdout: no JSON envelope
        from pbidriver import mcp_server

        return mcp_server.main(argv[1:])
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    from pbidriver.project import ProjectError

    try:
        result = args.func(args)
    except (DriverError, bridge.BridgeError, ProjectError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False))
        return 1
    except Exception as e:  # noqa: BLE001  Playwright/driver errors: keep the JSON contract
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)[:600]}"}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
