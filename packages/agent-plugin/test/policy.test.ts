import assert from "node:assert/strict";
import { test } from "node:test";

import { PolicyClient } from "../src/policy.ts";

const cfg = {
  baseUrl: "https://api.example.com",
  token: "persona-token",
  timeoutMs: 1000,
  failClosed: false,
  debug: false,
};

test("decide() posts the query and returns the decision", async () => {
  let seenUrl = "";
  let seenBody: any = null;
  const client = new PolicyClient(cfg, (async (url: string, init: RequestInit) => {
    seenUrl = url;
    seenBody = JSON.parse(init.body as string);
    return new Response(
      JSON.stringify({
        effect: "deny",
        reason: "nope",
        matched_rule: "baseline:rm-rf-root",
        mode: "enforce",
        enforced: true,
      }),
      { status: 200 },
    );
  }) as unknown as typeof fetch);

  const decision = await client.decide({
    tool: "bash",
    args: { command: "rm -rf /" },
    sessionRef: "s1",
  });

  assert.notEqual(decision, "unreachable");
  assert.equal(seenUrl, "https://api.example.com/policy/decide");
  assert.equal(seenBody.tool, "bash");
  assert.equal(seenBody.provenance, "trusted");
  assert.equal(seenBody.session_ref, "s1");
  if (decision !== "unreachable") {
    assert.equal(decision.effect, "deny");
    assert.equal(decision.enforced, true);
  }
});

test("decide() returns 'unreachable' when not configured", async () => {
  const client = new PolicyClient({ ...cfg, token: null });
  assert.equal(await client.decide({ tool: "bash" }), "unreachable");
});

test("decide() returns 'unreachable' on network error", async () => {
  const client = new PolicyClient(cfg, (async () => {
    throw new Error("boom");
  }) as typeof fetch);
  assert.equal(await client.decide({ tool: "bash" }), "unreachable");
});

test("decide() returns 'unreachable' on non-2xx", async () => {
  const client = new PolicyClient(cfg, (async () =>
    new Response("err", { status: 503 })) as typeof fetch);
  assert.equal(await client.decide({ tool: "bash" }), "unreachable");
});
