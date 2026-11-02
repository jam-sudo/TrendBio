import { execFileSync } from "node:child_process";

export default function setup() {
  execFileSync(process.execPath, ["node_modules/astro/astro.js", "build"], {
    env: { ...process.env, TRENDBIO_DATA_ROOT: "../fixtures/data", TRENDBIO_NOTES_ROOT: "../fixtures/notes" },
    stdio: "inherit",
  });
}
