import { cpSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import type { TestProject } from "vitest/node";

declare module "vitest" {
  export interface ProvidedContext { buildOutput: string }
}

export default function setup(project: TestProject) {
  const dataRoot = mkdtempSync(join(tmpdir(), "trendbio-map-fixture-"));
  cpSync("../fixtures/data", dataRoot, { recursive: true });
  cpSync("tests/fixtures/map.json", join(dataRoot, "computational/map.json"));
  cpSync("tests/fixtures/github_stars.json", join(dataRoot, "computational/github_stars.json"));
  const result = spawnSync(process.execPath, ["node_modules/astro/astro.js", "build"], {
    env: { ...process.env, FORCE_COLOR: "0", NO_COLOR: "1",
      TRENDBIO_DATA_ROOT: dataRoot, TRENDBIO_NOTES_ROOT: "../fixtures/notes" },
    encoding: "utf8",
  });
  rmSync(dataRoot, { recursive: true, force: true });
  process.stdout.write(result.stdout ?? "");
  process.stderr.write(result.stderr ?? "");
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Astro build failed: ${result.status}`);
  project.provide("buildOutput", (result.stdout + result.stderr).replace(/\x1b\[[0-9;]*m/g, ""));
}
