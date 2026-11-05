# Daily trigger

This dependency-free Cloudflare Worker dispatches `daily.yml` on `main` at
06:05 UTC. It is the recommended daily trigger: GitHub's scheduled runs have
arrived more than seven hours late in this repository. Keep GitHub `schedule`
enabled as backup. The Worker and manual kicks skip when a Daily run is queued,
in progress, or successful with a creation date of today (UTC), matching the
workflow's success-date guard.

## Enable

1. In GitHub **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**, choose resource owner `jam-sudo`,
   **Only select repositories → TrendBio** (`jam-sudo/TrendBio`), and a custom
   expiry one year from creation. Set repository permission **Actions: Read and
   write** only; GitHub's mandatory Metadata read access is automatic. See
   [GitHub's token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
2. Authenticate Cloudflare with `npx wrangler login`. Wrangler obtains the
   account ID from that login; set `CLOUDFLARE_ACCOUNT_ID` to select an account
   explicitly (or for existing noninteractive Cloudflare authentication).
3. From the repository root, run:

   ```sh
   cd ops/daily-trigger && npx wrangler secret put GITHUB_TOKEN && npx wrangler deploy
   ```

   Paste the GitHub token at the secret prompt. If Wrangler offers to create the
   Worker before uploading its first secret, accept. Never put the token in
   `wrangler.toml` or commit it. Renew it before expiry with
   `npx wrangler secret put GITHUB_TOKEN`.

No npm install or package dependencies are needed. Wrangler runs via `npx`.
[Cron changes can take up to 15 minutes to propagate](https://developers.cloudflare.com/workers/configuration/cron-triggers/).

## Test and inspect

Run the local self-test with Node 22.7+ (no credentials or network calls):

```sh
node test.mjs
```

After deployment, `GET /` returns `trendbio-daily-trigger ok`. To kick the real
pipeline manually, use the same GitHub token and the URL printed by deployment:

```sh
curl -X POST -H "Authorization: Bearer <token>" https://<worker>.workers.dev/run
```

Manual kicks apply the same guard as cron. A response of `202 dispatched` means
GitHub accepted the request, `200 skipped` means the guard matched, `401` means
the bearer is wrong or missing, and `502` means the GitHub request failed. A
missing configured secret is logged on cron; the status page only checks that
the Worker is reachable. Inspect logs with `npx wrangler tail` and confirm the
result in the repository's Actions tab.

The repository-runs lookup reads only ten recent runs and filters
their workflow paths locally: GitHub does not document `workflow` as a filter
for [that endpoint](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository). Busy repositories can therefore hide an older Daily run;
switch to paginated workflow-specific runs if volume grows. The check and
dispatch are not atomic, so simultaneous kicks can both dispatch before a run
becomes visible. The workflow retains its existing concurrency controls.

## Remove

From this directory, run `npx wrangler delete` and confirm deletion of
`trendbio-daily-trigger`. This removes the Worker, cron, and its secret. Revoke
the dedicated fine-grained token in GitHub settings. GitHub's schedule remains
available as backup; optionally delete this directory when retiring the setup.
