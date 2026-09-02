/**
 * Plugin configuration, resolved from the environment that `3pa` injects into the
 * sandbox (ADR-0009). Everything is optional so the plugin degrades quietly when
 * it is loaded outside a managed workstation.
 */

export interface PluginConfig {
  /** Backend base URL, e.g. https://agents.example.com */
  baseUrl: string | null;
  /** Persona bearer token (aud includes "audit"). */
  token: string | null;
  /** Per-request timeout for reporting calls, ms. */
  timeoutMs: number;
  /**
   * Phase 0: false — reporting failures are logged and swallowed so a developer
   * is never blocked by an audit outage.
   * Phase 1 (ADR-0006): flips to true — no audit sink means no tool execution.
   */
  failClosed: boolean;
  /** When true, print a line per reported event to stderr. */
  debug: boolean;
  /**
   * Tools whose output is treated as untrusted content for provenance / taint
   * tracking (ADR-0010). `null` → the plugin default set. Overridable via
   * `FABAGENT_TAINT_SOURCES` (comma-separated).
   */
  taintSources: string[] | null;
}

function envInt(env: NodeJS.ProcessEnv, name: string, fallback: number): number {
  const raw = env[name];
  if (!raw) return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function envBool(env: NodeJS.ProcessEnv, name: string, fallback: boolean): boolean {
  const raw = env[name];
  if (raw == null) return fallback;
  return raw === "1" || raw.toLowerCase() === "true";
}

function envList(env: NodeJS.ProcessEnv, name: string): string[] | null {
  const raw = env[name];
  if (!raw) return null;
  const items = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return items.length ? items : null;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): PluginConfig {
  const baseUrl = (env.FABAGENT_BASE_URL || "").replace(/\/+$/, "") || null;
  return {
    baseUrl,
    token: env.FABAGENT_TOKEN || null,
    timeoutMs: envInt(env, "FABAGENT_REPORT_TIMEOUT_MS", 3000),
    failClosed: envBool(env, "FABAGENT_FAIL_CLOSED", false),
    debug: envBool(env, "FABAGENT_DEBUG", false),
    taintSources: envList(env, "FABAGENT_TAINT_SOURCES"),
  };
}

export function isConfigured(cfg: PluginConfig): boolean {
  return Boolean(cfg.baseUrl && cfg.token);
}
