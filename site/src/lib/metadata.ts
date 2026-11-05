export function truncateDescription(description: string): string {
  const text = description.trim().replace(/\s+/g, " ");
  if (text.length <= 160) return text;
  const prefix = text.slice(0, 160);
  const boundary = prefix.lastIndexOf(" ");
  return `${prefix.slice(0, boundary > 0 ? boundary : 159)}…`;
}
