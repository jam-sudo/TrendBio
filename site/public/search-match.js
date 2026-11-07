function words(text) {
  // Match Pagefind's punctuation removal, including hyphenated and dotted names.
  return text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
    .replace(/[\p{Pd}\p{Pe}\p{Pf}\p{Pi}\p{Po}\p{Ps}]/gu, '')
    .match(/[\p{L}\p{N}]+/gu) ?? [];
}

function singular(word) {
  if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
  if (word.length > 3 && word.endsWith('s') && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
  return word;
}

export function matchesQuery(query, content) {
  const terms = words(query).filter(word => word.length >= 3).map(singular);
  const indexedWords = words(content).map(singular);
  // shortcut: preserve regular plurals, add fuller stemming if other inflections are needed.
  return terms.every(term => indexedWords.some(word => word.startsWith(term)));
}

export async function filterResults(query, candidates) {
  // shortcut: inspect only the first 50 candidates; revisit if deeper result browsing is needed.
  const results = await Promise.all(candidates.slice(0, 50).map(result => result.data()));
  return results.filter(result => matchesQuery(query, result.content));
}
