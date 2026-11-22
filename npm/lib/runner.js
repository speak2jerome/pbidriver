'use strict';
// Finds a way to run the pbidriver Python CLI. pbidriver drives Power BI Desktop through Windows APIs
// that only Python reaches well, so this package runs the same CLI rather than reimplementing it.
//
// Order:
//   1. PBIDRIVER_PYTHON=<python>     that interpreter, `-m pbidriver`
//   2. uvx (from uv), if installed   `uvx --from pbidriver==<version> pbidriver`, no Python setup needed
//   3. Python 3.9+ on PATH           `-m pbidriver`; installs pbidriver==<version> with pip once if missing
//                                    (set PBIDRIVER_NO_INSTALL=1 to never install)

const { spawnSync } = require('node:child_process');
const { version } = require('../package.json');

const PY_SPEC = `pbidriver==${version}`;

function output(command, args) {
  const r = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  return !r.error && r.status === 0 ? (r.stdout || '').trim() : null;
}

function compareVersions(a, b) {
  const pa = String(a).split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

function pythonCandidates() {
  return process.platform === 'win32'
    ? [['py', ['-3']], ['python', []], ['python3', []]]
    : [['python3', []], ['python', []]];
}

function pipInstall(command, prefix, log) {
  log(`installing the Python package ${PY_SPEC} (one time)...`);
  for (const extra of [['--user'], []]) { // --user fails inside a virtual environment; retry without it
    const r = spawnSync(command, [...prefix, '-m', 'pip', 'install', '--disable-pip-version-check', ...extra, PY_SPEC],
      { stdio: ['ignore', 2, 2], windowsHide: true }); // pip's output goes to stderr; stdout stays JSON-only
    if (!r.error && r.status === 0) return;
  }
  throw new Error(`Could not install ${PY_SPEC} with pip. Install it yourself (pip install ${PY_SPEC}) or install uv.`);
}

let cached = null;

/**
 * How to run pbidriver: { command, prefix, via }. The result is cached for the process.
 * @param {{install?: boolean, log?: (message: string) => void}} [options]
 */
function resolveRunner(options = {}) {
  if (cached) return cached;
  const install = options.install ?? !process.env.PBIDRIVER_NO_INSTALL;
  const log = options.log || ((message) => process.stderr.write(`pbidriver: ${message}\n`));

  const forced = process.env.PBIDRIVER_PYTHON;
  if (forced) {
    cached = { command: forced, prefix: ['-m', 'pbidriver'], via: 'PBIDRIVER_PYTHON' };
    return cached;
  }
  if (!process.env.PBIDRIVER_NO_UV && output('uvx', ['--version'])) {
    cached = { command: 'uvx', prefix: ['--quiet', '--from', PY_SPEC, 'pbidriver'], via: 'uvx' };
    return cached;
  }
  for (const [command, prefix] of pythonCandidates()) {
    if (output(command, [...prefix, '-c', 'import sys; print(sys.version_info >= (3, 9))']) !== 'True') continue;
    const installed = output(command, [...prefix, '-c', 'import pbidriver; print(pbidriver.__version__)']);
    if (!installed || compareVersions(installed, version) < 0) {
      if (!install) {
        throw new Error(`The Python package ${PY_SPEC} is not installed. Run: ${command} ${prefix.join(' ')} -m pip install ${PY_SPEC}`.replace(/ +/g, ' '));
      }
      pipInstall(command, prefix, log);
    }
    cached = { command, prefix: [...prefix, '-m', 'pbidriver'], via: command };
    return cached;
  }
  throw new Error('pbidriver needs Python 3.9 or later, or uv. Install Python from https://www.python.org/downloads/ '
    + 'or uv from https://docs.astral.sh/uv/, then run the command again.');
}

function resetRunner() {
  cached = null;
}

module.exports = { resolveRunner, resetRunner, compareVersions, PY_SPEC, version };
