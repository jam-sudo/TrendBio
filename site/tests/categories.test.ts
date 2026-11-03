import { describe, expect, it } from "vitest";
import { categoryIcon, categoryIdentity, categoryStyle, rankMedal } from "../src/lib/categories";
import { loadTaxonomy } from "../src/lib/data";

describe("shared category and rank identity", () => {
  it("covers every taxonomy category and has a safe unknown-category tile", () => {
    expect(Object.keys(categoryIdentity).sort()).toEqual(loadTaxonomy("computational").map(({ slug }) => slug).sort());
    expect(categoryStyle("structural")).toEqual({ icon: categoryIcon("structural"), hue: 240 });
    expect(categoryStyle("unknown")).toEqual({ icon: categoryIcon("unknown"), hue: 0 });
  });
  it("uses medals only for the top three ranks", () => {
    expect([1, 2, 3, 4, 5].map(rankMedal)).toEqual(["🥇", "🥈", "🥉", "4", "5"]);
  });
});
