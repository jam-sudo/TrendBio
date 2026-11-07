import type { APIRoute } from "astro";
import { topicPages } from "../../../lib/period-data";
import { bibtex, hasPapers, topicEvidence } from "../../../lib/citations";

export function getStaticPaths() {
  return topicPages().flatMap(topic => {
    const items = topicEvidence(topic);
    return hasPapers(items) ? [{ params: { slug: topic.slug }, props: { citations: bibtex(items) } }] : [];
  });
}

export const GET: APIRoute = ({ props }) => new Response(props.citations, {
  headers: { "Content-Type": "application/x-bibtex; charset=utf-8" },
});
