export type SurvivalStatus = 'PASS' | 'WARN' | 'FAIL' | 'N-A';
export type LayerMethod = { id: number; name: string; methodology: string; assumptions: string; minimum_data: string };
export type SurvivalLayer = LayerMethod & {
  status: SurvivalStatus;
  metrics: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  reasons: string[];
  hard_failure: boolean;
  gate_results: Record<string, unknown>[];
};
export type SurvivalSummary = {
  status: SurvivalStatus;
  counts: Record<SurvivalStatus, number>;
  hard_failures: number[];
  unresolved_required_layers: number[];
  unresolved_failure_gates: { layer: number; metric: string }[];
  research_gates_satisfied: boolean;
  live_eligible: false;
  interpretation: string;
};
export type SurvivalRun = {
  id: string;
  experiment_id: string;
  created_at: string;
  updated_at: string;
  name: string;
  input_hash: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  error: string | null;
  config: Record<string, unknown>;
  layers: SurvivalLayer[];
  cached?: boolean;
  result: null | {
    layers: SurvivalLayer[];
    summary: SurvivalSummary;
    provenance: Record<string, unknown>;
    strategy_version: string;
    synthetic: boolean;
    config: Record<string, unknown>;
  };
};
export type SurvivalBookEntry = Pick<SurvivalRun, 'id' | 'experiment_id' | 'created_at' | 'status' | 'error' | 'input_hash'> & { summary: SurvivalSummary | null };
export const survivalBase = '/integrations/engine/api/research/survival';

export function diagnosticValue(value: unknown): string {
  if (value === null || value === undefined) return 'N/A';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : 'N/A';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export function validateSurvivalConfig(text: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Validation configuration must be a JSON object.');
  return parsed as Record<string, unknown>;
}
