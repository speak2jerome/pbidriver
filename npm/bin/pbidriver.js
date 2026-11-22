#!/usr/bin/env node
'use strict';
// `pbidriver ...` / `npx pbidriver ...`: runs the pbidriver CLI with the same arguments, output and exit code.

const { spawn } = require('node:child_process');
const { resolveRunner } = require('../lib/runner');

function fail(message) {
  // Keep the CLI's contract: one JSON object on stdout, even when the wrapper itself fails.
  process.stdout.write(`${JSON.stringify({ ok: false, error: message }, null, 2)}\n`);
  process.exit(1);
}

let runner;
try {
  runner = resolveRunner();
} catch (e) {
  fail(e.message);
}

const child = spawn(runner.command, [...runner.prefix, ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('error', (e) => fail(`Could not start ${runner.command}: ${e.message}`));
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
