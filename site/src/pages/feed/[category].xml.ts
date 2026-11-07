import type { APIRoute } from "astro";
import { loadDays, loadTaxonomy } from "../../lib/data";
import { atomFeed } from "../../lib/feeds";

export function getStaticPaths() {
  return loadTaxonomy("computational").map(category => ({ params: { category: category.slug }, props: { category } }));
}

export const GET: APIRoute = ({ site, props }) => new Response(atomFeed(loadDays("computational"), site!, props.category), {
  headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
});
