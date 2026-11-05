import assert from "node:assert/strict";
import worker from "./src/index.js";

const env = {
  GITHUB_REPO: "jam-sudo/TrendBio",
  WORKFLOW_FILE: "daily.yml",
  REF: "main",
  GITHUB_TOKEN: "test-token",
};
const today = new Date().toISOString().slice(0, 10);
const daily = { path: ".github/workflows/daily.yml", created_at: `${today}T00:00:00Z` };
const base = "https://api.github.com/repos/jam-sudo/TrendBio/actions";
const originalFetch = globalThis.fetch;
let calls;

function stub(runs, { listStatus = 200, dispatchStatus = 204, throws = false, malformed = false } = {}) {
  calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    if (throws) throw new Error("simulated network failure");
    assert.equal(options.headers.Authorization, "Bearer test-token");
    assert.equal(options.headers.Accept, "application/vnd.github+json");
    assert.equal(options.headers["User-Agent"], "trendbio-daily-trigger");
    if (calls.length === 1) {
      assert.equal(url, `${base}/runs?workflow=daily.yml&per_page=10`);
      assert.equal(options.method ?? "GET", "GET");
      return new Response(malformed ? "invalid json" : JSON.stringify({ workflow_runs: runs }), { status: listStatus });
    }
    assert.equal(url, `${base}/workflows/daily.yml/dispatches`);
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), { ref: "main" });
    return new Response(null, { status: dispatchStatus });
  };
}

function kick(token = env.GITHUB_TOKEN, bindings = env) {
  return worker.fetch(new Request("https://example.workers.dev/run", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }), bindings);
}

try {
  for (const status of ["in_progress", "queued"]) {
    stub([{ ...daily, status }]);
    assert.equal(await (await kick()).text(), "skipped\n");
    assert.equal(calls.length, 1);
    console.log(`PASS skips ${status} Daily run`);
  }

  stub([{ ...daily, status: "completed", conclusion: "success" }]);
  assert.equal(await (await kick()).text(), "skipped\n");
  assert.equal(calls.length, 1);
  console.log("PASS skips success created today (UTC)");

  stub([
    { ...daily, status: "completed", conclusion: "success", created_at: "2000-01-01T00:00:00Z" },
    { ...daily, status: "completed", conclusion: "failure" },
    { ...daily, path: ".github/workflows/deploy.yml", status: "in_progress" },
    { ...daily, path: ".github/workflows/deploy.yml", conclusion: "success" },
  ]);
  assert.equal((await kick()).status, 202);
  assert.equal(calls.length, 2);
  console.log("PASS dispatches despite old success, failure, or unrelated workflow");

  stub([]);
  await worker.scheduled({}, env);
  assert.equal(calls.length, 2);
  console.log("PASS scheduled handler dispatches with no prior runs");

  stub([]);
  assert.equal((await kick("wrong-token")).status, 401);
  assert.equal((await kick("undefined", { ...env, GITHUB_TOKEN: undefined })).status, 401);
  assert.equal((await worker.fetch(new Request("https://example.workers.dev/run", { method: "POST" }), env)).status, 401);
  assert.equal(calls.length, 0);
  console.log("PASS manual run rejects wrong/missing bearer and missing secret");

  for (const options of [{ listStatus: 403 }, { dispatchStatus: 500 }, { throws: true }, { malformed: true }]) {
    stub([], options);
    assert.equal((await kick()).status, 502);
    assert.equal(calls.length, options.dispatchStatus ? 2 : 1);
  }
  stub([], { throws: true });
  await assert.doesNotReject(worker.scheduled({}, env));
  stub([]);
  await assert.doesNotReject(worker.scheduled({}, { ...env, GITHUB_TOKEN: undefined }));
  assert.equal(calls.length, 0);
  console.log("PASS API errors, malformed responses, and missing secret are handled");

  assert.equal(await (await worker.fetch(new Request("https://example.workers.dev/"), env)).text(), "trendbio-daily-trigger ok\n");
  assert.equal((await worker.fetch(new Request("https://example.workers.dev/run"), env)).status, 404);
  assert.equal(calls.length, 0);
  console.log("PASS status page and route handling");
  console.log("All daily-trigger tests passed.");
} finally {
  globalThis.fetch = originalFetch;
}
