import type { CustomRecord } from "pagefind";
import energy from "../../../docs/expansion-measurements/2026-11-23/energy.json";
import materials from "../../../docs/expansion-measurements/2026-11-21/materials.json";
import { editions, pilotDates } from "../lib/editions";
import { csReviewRows, pilotRows, pilotSearchRecord } from "../lib/pilot-topics";

export function GET() {
  const records: CustomRecord[] = editions.flatMap(field =>
    pilotDates(field).flatMap(date => pilotRows(field, date).map(row => pilotSearchRecord(field, row))));
  records.push(...csReviewRows().map(row => pilotSearchRecord("computer-information", row)));
  for (const { slug, label, collection } of [
    { slug: "materials", label: "Materials Science", collection: materials },
    { slug: "energy", label: "Energy Storage & Power Grids", collection: energy },
  ]) {
    records.push(...collection.groups.map(group => ({
      url: `/collections/${slug}/#${group.id}`, language: "en",
      content: [label, group.title, group.note, ...group.papers.map(p => p.title)].join(" "),
      filters: { field: [slug], category: [label] },
      meta: { title: group.title, field: `${label} · Collection · ${collection.end}` },
    })));
  }
  return Response.json(records);
}
