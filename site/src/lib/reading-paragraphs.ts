const sentences = new Intl.Segmenter("en", { granularity: "sentence" });

export function readingParagraphs(text: string): string[] {
  if (text.trim().split(/\s+/).length <= 90) return [text];
  const paragraphs: string[] = [];
  let current = "";
  let words = 0;
  for (const { segment } of sentences.segment(text)) {
    const count = segment.trim().split(/\s+/).length;
    const startsSentence = /^["“‘(]*(?:\p{Lu}|arXiv:|\d{4}\.\d{4,5}\b)/u.test(segment.trimStart());
    const abbreviated = /\b(?:et al|e\.g|i\.e|Fig|Eq|Ref|Dr|vs|No|[A-Z])\.$/i.test(current.trimEnd());
    if (words >= 35 && words + count > 75 && startsSentence && !abbreviated) {
      paragraphs.push(current.trim());
      current = "";
      words = 0;
    }
    current += segment;
    words += count;
  }
  paragraphs.push(current.trim());
  return paragraphs;
}
