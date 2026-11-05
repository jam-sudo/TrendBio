async function run(env) {
  try {
    if (!env.GITHUB_TOKEN) {
      console.error("GITHUB_TOKEN is not configured");
      return new Response("trigger not configured\n", { status: 503 });
    }
    const base = `https://api.github.com/repos/${env.GITHUB_REPO}/actions`;
    const workflow = encodeURIComponent(env.WORKFLOW_FILE);
    const headers = {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "trendbio-daily-trigger",
    };
    // shortcut: only ten recent repository runs are checked; use paginated workflow runs if volume grows.
    const response = await fetch(`${base}/runs?workflow=${workflow}&per_page=10`, { headers });
    if (!response.ok) {
      console.error(`GitHub runs status: ${response.status}`);
      return new Response("GitHub runs lookup failed\n", { status: 502 });
    }
    const { workflow_runs: runs } = await response.json();
    const today = new Date().toISOString().slice(0, 10);
    // The repository endpoint does not document a workflow query filter.
    const skip = runs.some((run) =>
      run.path === `.github/workflows/${env.WORKFLOW_FILE}` &&
      (run.status === "in_progress" || run.status === "queued" ||
        (run.conclusion === "success" && run.created_at.startsWith(today)))
    );
    if (skip) {
      console.log("skipped: workflow active or already succeeded today (UTC)");
      return new Response("skipped\n");
    }
    const dispatch = await fetch(`${base}/workflows/${workflow}/dispatches`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: env.REF }),
    });
    if (!dispatch.ok) {
      console.error(`GitHub dispatch status: ${dispatch.status}`);
      return new Response("GitHub dispatch failed\n", { status: 502 });
    }
    console.log(`GitHub dispatch status: ${dispatch.status}`);
    return new Response("dispatched\n", { status: 202 });
  } catch {
    console.error("trigger failed: network error or invalid GitHub response");
    return new Response("trigger failed\n", { status: 502 });
  }
}

export default {
  async scheduled(_event, env) {
    await run(env);
  },
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === "/") {
      return new Response("trendbio-daily-trigger ok\n");
    }
    if (request.method === "POST" && path === "/run") {
      if (!env.GITHUB_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.GITHUB_TOKEN}`) {
        return new Response("unauthorized\n", { status: 401 });
      }
      return run(env);
    }
    return new Response("not found\n", { status: 404 });
  },
};
