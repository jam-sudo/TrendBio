import { withGuidepup } from "@guidepup/playwright";

export default withGuidepup({
  testDir: ".",
  testMatch: "research.spec.ts",
  workers: 1,
  timeout: 180_000,
  use: { browserName: "chromium", baseURL: "https://trendbio.dev" },
});
