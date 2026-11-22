'use strict';
// Runs against the Python package in this repository (PBIDRIVER_PYTHON + PYTHONPATH), so no install or
// network is needed. None of these need Power BI Desktop.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const repo = path.resolve(__dirname, '..', '..');
process.env.PBIDRIVER_PYTHON = process.env.PBIDRIVER_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
process.env.PYTHONPATH = repo + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : '');

const { run, version } = require('..');
const { compareVersions } = require('../lib/runner');

test('npm and Python package versions match', () => {
  const init = fs.readFileSync(path.join(repo, 'pbidriver', '__init__.py'), 'utf8');
  assert.equal(init.match(/__version__ = "([^"]+)"/)[1], version);
});

test('run() resolves with the JSON result', async () => {
  const r = await run(['instances']);
  assert.equal(r.ok, true);
  assert.equal(typeof r.count, 'number');
  assert.ok(Array.isArray(r.instances));
});

test('run() resolves with ok: false for command errors', async () => {
  const r = await run(['launch', path.join(repo, 'no-such-report.pbix')]);
  assert.equal(r.ok, false);
  assert.match(r.error, /not found/i);
});

test('run() rejects when no JSON comes back', async () => {
  await assert.rejects(run(['--version']), /returned no JSON/);
});

test('the CLI shim passes output and exit codes through', () => {
  const bin = path.join(__dirname, '..', 'bin', 'pbidriver.js');
  const good = spawnSync(process.execPath, [bin, 'instances'], { encoding: 'utf8' });
  assert.equal(good.status, 0);
  assert.equal(JSON.parse(good.stdout).ok, true);
  const bad = spawnSync(process.execPath, [bin, 'launch', 'missing.pbix'], { encoding: 'utf8' });
  assert.equal(bad.status, 1);
  assert.equal(JSON.parse(bad.stdout).ok, false);
});

test('version comparison', () => {
  assert.ok(compareVersions('0.1.10', '0.1.9') > 0);
  assert.equal(compareVersions('0.1.1', '0.1.1'), 0);
  assert.ok(compareVersions('0.1', '0.1.1') < 0);
});
