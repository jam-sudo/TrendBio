import type { APIRoute } from "astro";
import { loadDays, loadTaxonomy } from "../../lib/data";
import { publicEditions } from "../../lib/editions";
import { atomFeed } from "../../lib/feeds";

export function getStaticPaths() {
  return publicEditions.flatMap(field => [
    { params: { field, feed: "feed" }, props: { field } },
    ...loadTaxonomy(field).map(category => ({
      params: { field, feed: `feed/${category.slug}` }, props: { field, category },
    })),
  ]);
}

export const GET: APIRoute = ({ props, site }) => new Response(
  atomFeed(loadDays(props.field), site!, props.category, props.field),
  { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } },
);
