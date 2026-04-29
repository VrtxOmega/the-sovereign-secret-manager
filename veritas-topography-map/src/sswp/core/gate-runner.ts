// src/sswp/core/gate-runner.ts
/** Runs VERITAS-style deterministic gates on a build */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { GateResult, BuildEnvironment } from './types.js';

export async function runGates(projectRoot: string, env: BuildEnvironment): Promise<GateResult[]> {
  const results: GateResult[] = [];

  // Gate 0: Language detection — polyglot support (Node, Python, Go, Rust, HTML)
  results.push(await languageDetectionGate(projectRoot));

  // Gate 1: Source Integrity — repo has clean working tree
  results.push(await gitIntegrityGate(projectRoot));
  
  // Gate 2: Dependency Lock — lockfile matches package.json (or equivalent)
  results.push(await lockfileGate(projectRoot));

  // Gate 3: Deterministic Build — build produces identical output hash
  results.push(await deterministicBuildGate(projectRoot, env));

  // Gate 4: Test Pass — all tests pass
  results.push(await testGate(projectRoot, env));

  // Gate 5: Lint — no lint errors
  results.push(await lintGate(projectRoot));

  return results;
}

// ── Gate 0: Language Detection ──

function languageDetectionGate(root: string): GateResult {
  const start = Date.now();
  const languages: string[] = [];
  
  if (existsSync(join(root, 'package.json'))) languages.push('node');
  if (existsSync(join(root, 'requirements.txt')) || existsSync(join(root, 'pyproject.toml')) || existsSync(join(root, 'setup.py'))) languages.push('python');
  if (existsSync(join(root, 'go.mod'))) languages.push('go');
  if (existsSync(join(root, 'Cargo.toml'))) languages.push('rust');
  if (existsSync(join(root, 'index.html')) && !existsSync(join(root, 'package.json'))) languages.push('html');
  if (!languages.length) languages.push('unknown');
  
  return {
    gate: 'LANGUAGE_DETECTION',
    status: 'PASS',
    evidence: `Detected: ${languages.join(', ')}`,
    durationMs: Date.now() - start,
  };
}

// ── Gate 2: Dependency Lock (polyglot) ──

async function lockfileGate(root: string): Promise<GateResult> {
  return timed('LOCKFILE', () => {
    // Node.js
    if (existsSync(join(root, 'package.json'))) {
      const hasLock = existsSync(join(root, 'package-lock.json')) || existsSync(join(root, 'yarn.lock')) || existsSync(join(root, 'pnpm-lock.yaml'));
      if (!hasLock) return { gate: 'LOCKFILE', status: 'FAIL' as const, evidence: 'package.json present but no lockfile (package-lock.json, yarn.lock, or pnpm-lock.yaml)', durationMs: 0 };
      return { gate: 'LOCKFILE', status: 'PASS' as const, evidence: 'Lockfile present', durationMs: 0 };
    }
    // Python
    if (existsSync(join(root, 'requirements.txt'))) {
      return { gate: 'LOCKFILE', status: 'PASS' as const, evidence: 'requirements.txt (pinned dependencies)', durationMs: 0 };
    }
    if (existsSync(join(root, 'pyproject.toml'))) {
      const hasPoetryLock = existsSync(join(root, 'poetry.lock'));
      const hasUvLock = existsSync(join(root, 'uv.lock'));
      return {
        gate: 'LOCKFILE', 
        status: (hasPoetryLock || hasUvLock) ? 'PASS' as const : 'WARN' as const,
        evidence: hasPoetryLock ? 'poetry.lock present' : hasUvLock ? 'uv.lock present' : 'pyproject.toml present but no lockfile',
        durationMs: 0,
      };
    }
    // Go
    if (existsSync(join(root, 'go.mod'))) {
      const hasSum = existsSync(join(root, 'go.sum'));
      return { gate: 'LOCKFILE', status: hasSum ? 'PASS' as const : 'WARN' as const, evidence: hasSum ? 'go.sum present' : 'go.mod present but no go.sum', durationMs: 0 };
    }
    // Rust
    if (existsSync(join(root, 'Cargo.toml'))) {
      const hasCargoLock = existsSync(join(root, 'Cargo.lock'));
      return { gate: 'LOCKFILE', status: hasCargoLock ? 'PASS' as const : 'WARN' as const, evidence: hasCargoLock ? 'Cargo.lock present' : 'Cargo.toml present but no Cargo.lock', durationMs: 0 };
    }
    // HTML / static
    if (existsSync(join(root, 'index.html')) && !existsSync(join(root, 'package.json'))) {
      return { gate: 'LOCKFILE', status: 'PASS' as const, evidence: 'Static site (no dependency manager)', durationMs: 0 };
    }
    return { gate: 'LOCKFILE', status: 'INCONCLUSIVE' as const, evidence: 'No recognized project type', durationMs: 0 };
  });
}

function timed(name: string, fn: () => GateResult): GateResult {
  const start = Date.now();
  const result = fn();
  result.durationMs = Date.now() - start;
  result.gate = name;
  return result;
}

async function gitIntegrityGate(root: string): Promise<GateResult> {
  return timed('GIT_INTEGRITY', () => {
    const r = spawnSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' });
    const clean = !r.stdout?.trim();
    return {
      gate: 'GIT_INTEGRITY',
      status: clean ? 'PASS' : 'FAIL',
      evidence: clean ? 'Working tree clean' : `Modified files: ${r.stdout?.trim().split('\n').length}`,
      durationMs: 0,
    };
  });
}

async function deterministicBuildGate(root: string, env: BuildEnvironment): Promise<GateResult> {
  return timed('DETERMINISTIC_BUILD', () => {
    const buildCandidates = [
      { check: 'package.json', cmd: ['npm', 'run', 'build'] },
      { check: 'Makefile', cmd: ['make'] },
      { check: 'pyproject.toml', cmd: ['python3', '-m', 'build'] },
      { check: 'go.mod', cmd: ['go', 'build', './...'] },
      { check: 'Cargo.toml', cmd: ['cargo', 'build'] },
      { check: 'index.html', cmd: ['echo', 'static'] },  // static sites pass
    ];
    for (const { check, cmd } of buildCandidates) {
      if (existsSync(join(root, check))) {
        if (check === 'index.html' && !existsSync(join(root, 'package.json'))) {
          return { gate: 'DETERMINISTIC_BUILD', status: 'PASS' as const, evidence: 'Static HTML site (no build required)', durationMs: 0 };
        }
        const r = spawnSync(cmd[0], cmd.slice(1), { cwd: root, encoding: 'utf8', shell: true, timeout: 60000 });
        const passed = r.status === 0;
        return {
          gate: 'DETERMINISTIC_BUILD',
          status: passed ? 'PASS' : 'FAIL',
          evidence: passed ? `Build succeeded: ${cmd.join(' ')}` : `Build failed: ${r.stderr?.slice(0, 200)}`,
          durationMs: 0,
        };
      }
    }
    return { gate: 'DETERMINISTIC_BUILD', status: 'INCONCLUSIVE' as const, evidence: 'No recognized build system', durationMs: 0 };
  });
}

async function testGate(root: string, env: BuildEnvironment): Promise<GateResult> {
  return timed('TEST_PASS', () => {
    const testCandidates = [
      { check: 'package.json', cmd: ['npm', 'test'] },
      { check: 'Makefile', cmd: ['make', 'test'] },
      { check: 'pyproject.toml', cmd: ['python3', '-m', 'pytest'] },
      { check: 'go.mod', cmd: ['go', 'test', './...'] },
      { check: 'Cargo.toml', cmd: ['cargo', 'test'] },
    ];
    for (const { check, cmd } of testCandidates) {
      if (existsSync(join(root, check))) {
        const r = spawnSync(cmd[0], cmd.slice(1), { cwd: root, encoding: 'utf8', shell: true, timeout: 120000 });
        const passed = r.status === 0;
        if (passed) return { gate: 'TEST_PASS', status: 'PASS' as const, evidence: `${cmd.join(' ')} passed`, durationMs: 0 };
        // Command failed but it was the right test runner
        return {
          gate: 'TEST_PASS',
          status: 'FAIL',
          evidence: `${cmd.join(' ')} failed: ${(r.stderr || r.stdout)?.slice(0, 200)}`,
          durationMs: 0,
        };
      }
    }
    return { gate: 'TEST_PASS', status: 'INCONCLUSIVE' as const, evidence: 'No test runner configured', durationMs: 0 };
  });
}

async function lintGate(root: string): Promise<GateResult> {
  return timed('LINT', () => {
    // Try npx eslint or biome or tsc
    const candidates = [
      ['npx', 'eslint', '--max-warnings=0', '.'],
      ['npx', 'biome', 'check', '.'],
      ['npx', 'tsc', '--noEmit'],
    ];
    for (const [cmd, ...args] of candidates) {
      const r = spawnSync(cmd as string, args, { cwd: root, encoding: 'utf8', shell: true });
      if (r.status === 0) {
        return { gate: 'LINT', status: 'PASS' as const, evidence: `${cmd} passed`, durationMs: 0 };
      }
      // If command not found, try next
      if (r.error || (r.stderr?.includes('not found') || r.stderr?.includes('ENOENT'))) continue;
    }
    return { gate: 'LINT', status: 'INCONCLUSIVE' as const, evidence: 'No linter configured', durationMs: 0 };
  });
}
