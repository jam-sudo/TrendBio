import type { APIRoute } from "astro";
import { topicPages } from "../../../../lib/period-data";
import { bibtex, hasPapers, topicEvidence, topicSnapshot } from "../../../../lib/citations";
import { allTopics } from "../../../../lib/data";
import { publicEditions, topicAppearances, type Field } from "../../../../lib/editions";

export function getStaticPaths() {
  const fields: Field[] = ["computational", ...publicEditions];
  return fields.flatMap(field => {
    const topics = field === "computational" ? topicPages() : allTopics(field).filter(topic => topicAppearances(field).has(topic.slug));
    return topics.flatMap(topic => {
      const items = topicEvidence(topic, topicSnapshot(topic, field));
      const params = { field: field === "computational" ? undefined : field, slug: topic.slug };
      return hasPapers(items) ? [{ params, props: { citations: bibtex(items) } }] : [];
    });
  });
}

export const GET: APIRoute = ({ props }) => new Response(props.citations, {
  headers: { "Content-Type": "application/x-bibtex; charset=utf-8" },
});
