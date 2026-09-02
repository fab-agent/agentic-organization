import assert from "node:assert/strict";
import { test } from "node:test";

import { isConfigured, loadConfig } from "../src/config.ts";
import { Reporter } from "../src/reporter.ts";

const baseCfg = {
  baseUrl: "https://api.example.com",
  token: "persona-token",
  timeoutMs: 1000,
  failClosed: false,
  debug: false,
  taintSources: null,
};

test("loadConfig reads and normalises env", () => {
  const cfg = loadConfig({
    FABAGENT_BASE_URL: "https://api.example.com/",
    FABAGENT_TOKEN: "tok",
    FABAGENT_REPORT_TIMEOUT_MS: "500",
    FABAGENT_FAIL_CLOSED: "1",
  } as NodeJS.ProcessEnv);
  assert.equal(cfg.baseUrl, "https://api.example.com");
  assert.equal(cfg.token, "tok");
  assert.equal(cfg.timeoutMs, 500);
  assert.equal(cfg.failClosed, true);
  assert.equal(isConfigured(cfg), true);
});

test("isConfigured is false without base url or token", () => {
  assert.equal(isConfigured(loadConfig({} as NodeJS.ProcessEnv)), false);
});

test("report() skips when not configured", async () => {
  let called = false;
  const reporter = new Reporter(
    { ...baseCfg, baseUrl: null },
    (async () => {
      called = true;
      return new Response("", { status: 200 });
    }) as typeof fetch,
  );
  const outcome = await reporter.report({ phase: "before", tool: "bash" });
  assert.equal(outcome, "skipped");
  assert.equal(called, false);
});

test("report() posts a normalised payload and returns ok", async () => {
  const seen: { url: string; init: RequestInit } = { url: "", init: {} };
  const reporter = new Reporter(baseCfg, (async (url: string, init: RequestInit) => {
    seen.url = url;
    seen.init = init;
    return new Response(JSON.stringify({ accepted: true }), { status: 202 });
  }) as unknown as typeof fetch);

  const outcome = await reporter.report({
    phase: "before",
    tool: "bash",
    sessionRef: "sess_1",
    argsPreview: { command: "git status" },
    provenance: "untrusted",
  });

  assert.equal(outcome, "ok");
  assert.equal(seen.url, "https://api.example.com/workstation/tool-event");
  const body = JSON.parse(seen.init.body as string);
  assert.equal(body.phase, "before");
  assert.equal(body.tool, "bash");
  assert.equal(body.session_ref, "sess_1");
  assert.deepEqual(body.args_preview, { command: "git status" });
  assert.equal(body.provenance, "untrusted");
  assert.ok(body.client_ts);
  assert.equal(
    (seen.init.headers as Record<string, string>).Authorization,
    "Bearer persona-token",
  );
});

test("report() returns unreachable on network error", async () => {
  const reporter = new Reporter(baseCfg, (async () => {
    throw new Error("ECONNREFUSED");
  }) as typeof fetch);
  const outcome = await reporter.report({ phase: "after", tool: "webfetch" });
  assert.equal(outcome, "unreachable");
});

test("report() returns unreachable on non-2xx", async () => {
  const reporter = new Reporter(baseCfg, (async () =>
    new Response("nope", { status: 500 })) as typeof fetch);
  const outcome = await reporter.report({ phase: "before", tool: "edit" });
  assert.equal(outcome, "unreachable");
});
