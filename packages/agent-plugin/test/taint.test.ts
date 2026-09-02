import assert from "node:assert/strict";
import { test } from "node:test";

import { loadConfig } from "../src/config.ts";
import { DEFAULT_TAINT_SOURCES, SessionTaint } from "../src/taint.ts";

test("a fresh session is trusted", () => {
  const t = new SessionTaint();
  assert.equal(t.provenanceFor("s1"), "trusted");
  assert.equal(t.isTainted("s1"), false);
});

test("a taint-source tool marks the session untrusted, stickily", () => {
  const t = new SessionTaint();
  t.observe("s1", "webfetch");
  assert.equal(t.provenanceFor("s1"), "untrusted");
  // sticky — a later benign tool does not clear it
  t.observe("s1", "read");
  assert.equal(t.provenanceFor("s1"), "untrusted");
});

test("taint is per-session", () => {
  const t = new SessionTaint();
  t.observe("s1", "webfetch");
  assert.equal(t.provenanceFor("s2"), "trusted");
});

test("non-source tools never taint", () => {
  const t = new SessionTaint();
  for (const tool of ["read", "bash", "write", "edit", "grep", "glob"]) {
    t.observe("s1", tool);
  }
  assert.equal(t.provenanceFor("s1"), "trusted");
});

test("default sources cover opencode's web tools, case-insensitively", () => {
  const t = new SessionTaint();
  assert.ok(t.isSource("webfetch"));
  assert.ok(t.isSource("WebFetch"));
  assert.ok(t.isSource("web_search"));
  assert.ok(DEFAULT_TAINT_SOURCES.includes("webfetch"));
});

test("sources are overridable and the no-session bucket works", () => {
  const t = new SessionTaint(["email", "a2a"]);
  assert.equal(t.isSource("webfetch"), false);
  t.observe(null, "email");
  assert.equal(t.provenanceFor(null), "untrusted");
  assert.equal(t.provenanceFor(undefined), "untrusted");
});

test("FABAGENT_TAINT_SOURCES parses into config", () => {
  const cfg = loadConfig({
    FABAGENT_TAINT_SOURCES: " webfetch , email ,, a2a ",
  } as NodeJS.ProcessEnv);
  assert.deepEqual(cfg.taintSources, ["webfetch", "email", "a2a"]);

  const t = new SessionTaint(cfg.taintSources ?? undefined);
  assert.ok(t.isSource("email"));

  assert.equal(loadConfig({} as NodeJS.ProcessEnv).taintSources, null);
});
