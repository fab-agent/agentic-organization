/**
 * SessionTaint — tracks which opencode sessions have ingested untrusted content
 * (ADR-0010, provenance / taint separation).
 *
 * opencode's plugin surface has no message-provenance model, so we approximate
 * it at the session level: once a session runs a tool whose OUTPUT is
 * attacker-controllable (web fetch, web search, …), every later tool call in
 * that session is reported to the Policy Engine with `provenance: "untrusted"`.
 *
 * Taint is **sticky** — untrusted content, once in the context window, can
 * influence every subsequent turn, so there is no un-taint. It is also
 * per-session: a fresh opencode session starts clean.
 *
 * The set of taint-source tools is overridable via `FABAGENT_TAINT_SOURCES`
 * (comma-separated) so an org can widen it (e.g. a custom `email` tool) without
 * a plugin release.
 */

export const DEFAULT_TAINT_SOURCES = [
  "webfetch",
  "fetch",
  "websearch",
  "web_search",
  "web-search",
];

const NO_SESSION = "__no_session__";

export class SessionTaint {
  private readonly tainted = new Set<string>();
  private readonly sources: Set<string>;

  constructor(sources: Iterable<string> = DEFAULT_TAINT_SOURCES) {
    this.sources = new Set(
      [...sources].map((s) => s.trim().toLowerCase()).filter(Boolean),
    );
  }

  /** True if this tool's output should be treated as untrusted content. */
  isSource(tool: string): boolean {
    return this.sources.has((tool || "").toLowerCase());
  }

  /**
   * Record that a tool ran to completion in a session. Marks the session
   * tainted when the tool is a taint source. Call from `tool.execute.after`.
   */
  observe(sessionRef: string | null | undefined, tool: string): void {
    if (this.isSource(tool)) this.tainted.add(key(sessionRef));
  }

  /** Provenance to report for the next tool call in this session. */
  provenanceFor(
    sessionRef: string | null | undefined,
  ): "trusted" | "untrusted" {
    return this.tainted.has(key(sessionRef)) ? "untrusted" : "trusted";
  }

  isTainted(sessionRef: string | null | undefined): boolean {
    return this.tainted.has(key(sessionRef));
  }
}

function key(sessionRef: string | null | undefined): string {
  return sessionRef ?? NO_SESSION;
}
