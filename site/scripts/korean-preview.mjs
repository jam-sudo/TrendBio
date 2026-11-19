import { localizePreview } from './localize.mjs';

// Astro renders the same English route, including its current development edits.
export async function koreanPreview(request, response, next) {
  const route = new URL(request.url, 'http://localhost');
  if (!/^\/ko(?:\/|$)/.test(route.pathname)) return next();
  const host = request.socket.localAddress;
  const origin = new URL(
    'http://' + (host.includes(':') ? '[' + host + ']' : host) + ':' + request.socket.localPort,
  );
  origin.pathname = '/' + route.pathname.slice(3).replace(/^\/+/, '');
  origin.search = route.search;
  if (/^\/ko(?:\/|$)/.test(origin.pathname)) return next();
  const upstream = await fetch(origin, { redirect: 'manual' });
  response.statusCode = upstream.status;
  const location = upstream.headers.get('location');
  if (location) {
    const target = new URL(location, origin);
    response.setHeader('Location', '/ko' + target.pathname + target.search + target.hash);
  }
  const type = upstream.headers.get('content-type') || 'application/octet-stream';
  response.setHeader('Content-Type', type);
  if (
    type.startsWith('text/html') ||
    type.includes('application/atom+xml') ||
    origin.pathname === '/map.json'
  ) {
    const file = type.startsWith('text/html') ? 'index.html' : origin.pathname;
    return response.end(localizePreview(await upstream.text(), file));
  }
  response.end(Buffer.from(await upstream.arrayBuffer()));
}
