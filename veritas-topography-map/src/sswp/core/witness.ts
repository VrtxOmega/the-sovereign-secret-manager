// src/sswp/core/witness.ts
/** SSWP orchestrator — builds, seals, and attests */

import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { seal } from '../../engine/sealer.js';
import { scanBuild } from './build-scanner.js';
import { runGates } from './gate-runner.js';
import { runAdversarialProbes } from './adversarial-probe.js';
import type { SswpAttestation, BuildEnvironment } from './types.js';

export async function witness(projectRoot: string): Promise<SswpAttestation> {
  // Phase 0: Detect project type (polyglot support)
  const projectType = detectProjectType(projectRoot);
  const projectName = resolveProjectName(projectRoot, projectType);

  // Phase 1: Scan (skip dependency scan for non-Node static sites)
  let entries: any[] = [];
  let env: BuildEnvironment = { nodeVersion: process.version, os: process.platform, arch: process.arch, ci: !!process.env.CI, buildCommand: 'unknown' };
  let totalPackages = 0;
  let suspiciousCount = 0;

  if (projectType !== 'html' && existsSync(join(projectRoot, 'package.json'))) {
    const scan = await scanBuild(projectRoot);
    entries = scan.entries;
    env = scan.env;
    totalPackages = scan.totalPackages;
    suspiciousCount = scan.suspiciousCount;
  }

  const scanSeal = seal(
    { phase: 'SCAN', totalPackages, suspiciousCount, projectType },
    `Scanned ${totalPackages} packages, ${suspiciousCount} flagged (type: ${projectType})`
  );

  // Phase 2: Gates
  const gateResults = await runGates(projectRoot, env);
  const passedGates = gateResults.filter(g => g.status === 'PASS').length;

  const gateSeal = seal(
    { phase: 'GATES', passed: passedGates, total: gateResults.length },
    JSON.stringify(gateResults.map(g => ({ gate: g.gate, status: g.status })))
  );

  // Phase 3: Adversarial (only for Node repos with deps)
  let adversarial = { totalPackages: 0, suspiciousPackages: 0, probes: [], overallRisk: 0 };
  if (entries.length > 0) {
    adversarial = await runAdversarialProbes(entries);
  }

  const advSeal = seal(
    { phase: 'ADVERSARIAL', overallRisk: adversarial.overallRisk, probes: adversarial.probes.length },
    JSON.stringify(adversarial)
  );

  // Phase 4: Attest
  const gitHash = execGit(projectRoot, ['rev-parse', 'HEAD']);
  const branch = execGit(projectRoot, ['rev-parse', '--abbrev-ref', 'HEAD']);

  const attestation: SswpAttestation = {
    version: '1.1.0',
    timestamp: new Date().toISOString(),
    projectType,
    target: {
      name: projectName,
      repo: projectRoot,
      commitHash: gitHash || 'unknown',
      branch: branch || 'unknown',
    },
    environment: {
      nodeVersion: env.nodeVersion,
      os: env.os,
      arch: env.arch,
      ci: env.ci,
    },
    dependencies: entries,
    gates: gateResults,
    adversarial,
    seal: {
      chainHash: scanSeal.hash,
      sequence: (gateSeal?.sequence ?? 0) + (advSeal?.sequence ?? 0),
    },
    signature: '',
  };

  const { signature, ...hashPayload } = attestation;
  attestation.signature = createHash('sha256').update(JSON.stringify(hashPayload, Object.keys(hashPayload).sort())).digest('hex');

  const finalSeal = seal(
    { phase: 'ATTEST', signature: attestation.signature },
    'Attestation sealed and signed'
  );

  return attestation;
}

// ── Polyglot helpers ──

function detectProjectType(root: string): string {
  if (existsSync(join(root, 'package.json'))) return 'node';
  if (existsSync(join(root, 'requirements.txt')) || existsSync(join(root, 'pyproject.toml')) || existsSync(join(root, 'setup.py'))) return 'python';
  if (existsSync(join(root, 'go.mod'))) return 'go';
  if (existsSync(join(root, 'Cargo.toml'))) return 'rust';
  if (existsSync(join(root, 'index.html'))) return 'html';
  return 'unknown';
}

function resolveProjectName(root: string, projectType: string): string {
  try {
    if (projectType === 'node') {
      const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
      return pkg.name || root.split('/').pop() || 'unknown';
    }
    if (projectType === 'python') {
      if (existsSync(join(root, 'pyproject.toml'))) {
        const toml = readFileSync(join(root, 'pyproject.toml'), 'utf8');
        const match = toml.match(/name\s*=\s*"(.+)"/);
        if (match) return match[1];
      }
    }
    if (projectType === 'go') {
      const gomod = readFileSync(join(root, 'go.mod'), 'utf8');
      const match = gomod.match(/module\s+(.+)/);
      if (match) return match[1].split('/').pop() || match[1];
    }
  } catch {}
  return root.split('/').pop() || 'unknown';
}

function execGit(cwd: string, args: string[]): string {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  return r.stdout?.trim() || '';
}

export function formatAttestation(att: SswpAttestation): string {
  const lines: string[] = [];
  lines.push(`\u2b21  SSWP ATTESTATION v${att.version}`);
  lines.push(`   Target: ${att.target.name} (${att.target.commitHash.slice(0, 8)})`);
  lines.push(`   Branch: ${att.target.branch} | Env: ${att.environment.os}-${att.environment.arch}`);
  lines.push(`   Built: ${att.timestamp}`);
  lines.push('');
  lines.push('   GATES:');
  for (const g of att.gates) {
    const icon = g.status === 'PASS' ? '\u2713' : g.status === 'FAIL' ? '\u2717' : '\u25cb';
    lines.push(`     ${icon} ${g.gate.padEnd(22)} ${g.status.padEnd(14)} ${g.durationMs}ms`);
  }
  lines.push('');
  lines.push(`   DEPENDENCIES: ${att.dependencies.length} total, ${att.adversarial.suspiciousPackages} flagged`);
  lines.push(`   ADVERSARIAL RISK: ${(att.adversarial.overallRisk * 100).toFixed(1)}%`);
  lines.push(`   SEAL: ${att.signature.slice(0, 16)}...`);
  return lines.join('\n');
}

export function verifyAttestation(filePath: string): boolean {
  const att = JSON.parse(readFileSync(filePath, 'utf8'));
  const { signature, ...hashPayload } = att;
  const payload = JSON.stringify(hashPayload, Object.keys(hashPayload).sort());
  const computed = createHash('sha256').update(payload).digest('hex');
  return computed === att.signature;
}
