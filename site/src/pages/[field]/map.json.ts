import type { APIRoute } from "astro";
import { loadMap } from "../../lib/data";
import { publicEditions } from "../../lib/editions";

export const getStaticPaths = () => publicEditions.map(field => ({ params: { field } }));
export const GET: APIRoute = ({ params }) => Response.json(loadMap(params.field!));
