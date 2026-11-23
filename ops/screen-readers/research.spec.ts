import { expect } from "@playwright/test";
import { screenReaderTest as test } from "@guidepup/playwright";

test("read a search result and open its supporting paper", async ({ page, screenReader }) => {
  await page.goto("/computer-information/");
  await screenReader.navigateToWebContent();
  const search = page.locator("#header-search-query");
  await search.focus();
  await page.keyboard.type("regret");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/field=computer-information/);
  const result = page.locator('#search-results a[href$="#review-2026-11-18-9"]');
  await expect(result).toBeVisible();

  async function hear(label: string, action: () => Promise<unknown>, expected: RegExp) {
    const { spokenPhrase } = await screenReader.capture(action, { capture: true });
    console.log(screenReader.name, label, JSON.stringify(spokenPhrase));
    expect(spokenPhrase).toMatch(expected);
  }

  const broaden = page.getByRole("link", { name: "Search all fields" });
  for (let step = 0; step < 32 && !await broaden.evaluate(el => el === document.activeElement); step++) {
    await page.keyboard.press("Tab");
  }
  await expect(broaden).toBeFocused();
  await hear("search result", () => page.keyboard.press("Tab"), /regret bounds for bandits/i);
  await expect(result).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#review-2026-11-18-9$/);
  const rank = page.locator(":target");
  await expect(rank).toHaveAttribute("value", "9");
  const summary = rank.locator("details > summary");
  await hear("rank evidence", () => page.keyboard.press("Tab"), /supporting papers.* for rank 9/i);
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  const paper = rank.locator("details a").first();
  await expect(paper).toBeVisible();
  await hear("first paper", () => page.keyboard.press("Tab"), /oracle.efficient adversarial contextual bandits/i);
  const url = await paper.getAttribute("href");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(url!);
});
