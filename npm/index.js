'use strict';
// JavaScript API: run a pbidriver command and get its JSON result.
//
//   const { run } = require('pbidriver');
//   const shot = await run(['shot', '--page', 'Overview', '--annotate']);
//   if (shot.ok) console.log(shot.file);

const { spawn } = require('node:child_process');
const { resolveRunner, version } = require('./lib/runner');

/**
 * Run one pbidriver command, e.g. run(['read', '--visual', '3']).
 * Resolves with the command's JSON object (check `ok`); rejects only when no JSON came back.
 */
function run(args, options = {}) {
  return new Promise((resolve, reject) => {
    let runner;
    try {
      runner = resolveRunner();
    } catch (e) {
      reject(e);
      return;
    }
    const child = spawn(runner.command, [...runner.prefix, ...args.map(String)], {
      cwd: options.cwd,
      env: { ...process.env, ...(options.env || {}) },
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8').on('data', (d) => { stdout += d; });
    child.stderr.setEncoding('utf8').on('data', (d) => { stderr += d; });
    const timer = options.timeout ? setTimeout(() => child.kill(), options.timeout) : null;
    child.on('error', (e) => {
      if (timer) clearTimeout(timer);
      reject(e);
    });
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      try {
        const result = JSON.parse(stdout.trim());
        Object.defineProperty(result, 'stderr', { value: stderr, enumerable: false });
        resolve(result);
      } catch {
        const e = new Error(`pbidriver returned no JSON (exit code ${code}): ${(stderr || stdout).trim().slice(0, 500)}`);
        Object.assign(e, { exitCode: code, stdout, stderr });
        reject(e);
      }
    });
  });
}

module.exports = { run, resolveRunner, version };
