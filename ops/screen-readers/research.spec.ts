import { expect } from "@playwright/test";
import { screenReaderTest as test } from "@guidepup/playwright";

test("read a search result and open its supporting paper", async ({ page, screenReader }) => {
  await page.goto("/search/?q=regret&field=computer-information");
  const result = page.locator('#search-results a[href$="#review-2026-11-18-9"]');
  await expect(result).toBeVisible();
  await screenReader.navigateToWebContent();

  async function hear(label: string, action: () => Promise<unknown>, expected: RegExp) {
    const { spokenPhrase } = await screenReader.capture(action, { capture: true });
    console.log(screenReader.name, label, JSON.stringify(spokenPhrase));
    expect(spokenPhrase).toMatch(expected);
  }

  await hear("search result", () => result.focus(), /regret bounds for bandits/i);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#review-2026-11-18-9$/);
  const rank = page.locator(":target");
  await expect(rank).toHaveAttribute("value", "9");
  const summary = rank.locator("details > summary");
  await hear("rank evidence", () => summary.focus(), /supporting papers.*rank 9/i);
  await page.keyboard.press("Enter");
  const paper = rank.locator("details a").first();
  await expect(paper).toBeVisible();
  await hear("first paper", () => page.keyboard.press("Tab"), /oracle.efficient adversarial contextual bandits/i);
  const url = await paper.getAttribute("href");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(url!);
});
