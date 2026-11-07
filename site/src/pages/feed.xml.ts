import type { APIRoute } from "astro";
import { loadDays } from "../lib/data";
import { atomFeed } from "../lib/feeds";

export const GET: APIRoute = ({ site }) => new Response(atomFeed(loadDays("computational"), site!), {
  headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
});
