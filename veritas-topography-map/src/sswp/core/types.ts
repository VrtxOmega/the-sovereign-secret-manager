// src/sswp/core/types.ts
/** Sovereign Software Witness Protocol — Core Types (v1.1 polyglot) */

export interface SswpAttestation {
  id?: string;
  version: string;
  timestamp: string;
  projectType?: string; // node | python | go | rust | html | unknown
  target: {
    name: string;
    repo: string;
    commitHash: string;
    branch: string;
  };
  environment: {
    nodeVersion: string;
    os: string;
    arch: string;
    ci: boolean;
  };
  dependencies: DependencyEntry[];
  gates: GateResult[];
  adversarial: AdversarialReport;
  seal: {
    chainHash: string;
    sequence: number;
  };
  signature: string; // sha256 of attestation JSON
}

export interface DependencyEntry {
  name: string;
  version: string;
  resolved: string;
  integrity: string | null;
  suspicious: boolean;
  riskScore: number; // 0-1
}

export interface GateResult {
  gate: string;
  status: 'PASS' | 'FAIL' | 'INCONCLUSIVE';
  evidence: string;
  durationMs: number;
}

export interface AdversarialReport {
  totalPackages: number;
  suspiciousPackages: number;
  probes: ProbeResult[];
  overallRisk: number; // 0-1
}

export interface ProbeResult {
  package: string;
  probe: string;
  result: 'PASS' | 'WARN' | 'CRITICAL' | 'INCONCLUSIVE';
  detail: string;
}

export interface BuildEnvironment {
  cwd: string;
  nodeVersion: string;
  os: string;
  arch: string;
  ci: boolean;
  buildCommand: string;
  buildOutput: string;
}
