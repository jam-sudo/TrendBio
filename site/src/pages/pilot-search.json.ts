import type { CustomRecord } from "pagefind";
import materials from "../../../docs/expansion-measurements/2026-11-21/materials.json";
import { editions, pilotDates } from "../lib/editions";
import { csReviewRows, pilotRows, pilotSearchRecord } from "../lib/pilot-topics";

export function GET() {
  const records: CustomRecord[] = editions.flatMap(field =>
    pilotDates(field).flatMap(date => pilotRows(field, date).map(row => pilotSearchRecord(field, row))));
  records.push(...csReviewRows().map(row => pilotSearchRecord("computer-information", row)));
  records.push(...materials.groups.map(group => ({
    url: `/collections/materials/#${group.id}`, language: "en",
    content: [group.title, group.note, ...group.papers.map(p => p.title)].join(" "),
    filters: { field: ["materials"], category: ["Materials Science"] },
    meta: { title: group.title, field: `Materials Science · Collection · ${materials.end}` },
  })));
  return Response.json(records);
}
