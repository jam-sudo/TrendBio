import { readFile } from "node:fs/promises";
import { createIndex, close } from "pagefind";

function checked(response) {
  if (response.errors.length) throw Error(response.errors.join("\n"));
  return response;
}

try {
  const { index } = checked(await createIndex());
  checked(await index.addDirectory({ path: "dist", glob: "**/topic/*/index.html" }));
  const records = JSON.parse(await readFile("dist/pilot-search.json", "utf8"));
  for (const record of records) checked(await index.addCustomRecord(record));
  checked(await index.writeFiles({ outputPath: "dist/pagefind" }));
} finally {
  await close();
}
