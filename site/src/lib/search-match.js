function words(text) {
  // Match Pagefind's punctuation removal, including hyphenated and dotted names.
  return text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').normalize('NFC')
    .replace(/[\p{Pd}\p{Pe}\p{Pf}\p{Pi}\p{Po}\p{Ps}]/gu, '')
    .match(/[\p{L}\p{N}]+/gu) ?? [];
}

function singular(word) {
  if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
  if (word.length > 3 && word.endsWith('s') && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
  return word;
}

export function matchesQuery(query, content) {
  const terms = words(query).filter(word => word.length >= 3 || /[가-힣]/.test(word)).map(singular);
  const indexedWords = words(content).map(singular);
  // shortcut: preserve regular plurals, add fuller stemming if other inflections are needed.
  return terms.every(term => indexedWords.some(word => word.startsWith(term)));
}

export async function filterResults(query, candidates) {
  const results = await Promise.all(candidates.map(result => result.data()));
  return results.filter(result => matchesQuery(query, result.content));
}

export function matchingPages(query, candidates, size = 20) {
  let offset = 0, shown = 0;
  const matches = [];
  return {
    async next(isCurrent) {
      while (matches.length < shown + size && offset < candidates.length) {
        if (!isCurrent()) return null;
        const batch = candidates.slice(offset, offset + size);
        const found = await filterResults(query, batch);
        if (!isCurrent()) return null;
        matches.push(...found);
        offset += batch.length;
      }
      if (!isCurrent()) return null;
      const page = matches.slice(shown, shown + size);
      shown += page.length;
      const complete = offset === candidates.length;
      return { page, shown, count: matches.length, complete, more: !complete || shown < matches.length };
    },
  };
}

export async function firstMatches(query, candidates, isCurrent) {
  const matches = [];
  let offset = 0;
  while (matches.length < 6 && offset < candidates.length && isCurrent()) {
    const batch = candidates.slice(offset, offset + 6 - matches.length);
    matches.push(...await filterResults(query, batch));
    offset += batch.length;
  }
  return isCurrent() ? matches : [];
}
