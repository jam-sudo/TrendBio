import { loadMap } from "../lib/data";

// Astro emits this static file so large maps can be fetched instead of embedded.
export function GET() {
  return new Response(JSON.stringify(loadMap("computational")), {
    headers: { "Content-Type": "application/json" },
  });
}
