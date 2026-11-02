import { spawnSync } from "node:child_process";
import type { TestProject } from "vitest/node";

declare module "vitest" {
  export interface ProvidedContext { buildOutput: string }
}

export default function setup(project: TestProject) {
  const result = spawnSync(process.execPath, ["node_modules/astro/astro.js", "build"], {
    env: { ...process.env, FORCE_COLOR: "0", NO_COLOR: "1",
      TRENDBIO_DATA_ROOT: "../fixtures/data", TRENDBIO_NOTES_ROOT: "../fixtures/notes" },
    encoding: "utf8",
  });
  process.stdout.write(result.stdout ?? "");
  process.stderr.write(result.stderr ?? "");
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Astro build failed: ${result.status}`);
  project.provide("buildOutput", (result.stdout + result.stderr).replace(/\x1b\[[0-9;]*m/g, ""));
}
