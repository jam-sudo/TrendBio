import matcherUrl from './search-match.js?url&no-inline';

let pending;
let failures = 0;

export function loadSearch() {
  if (!pending) {
    // Browsers can cache a failed module URL for the lifetime of the document.
    const retry = failures ? `?retry=${failures}` : '';
    const urls = ['/pagefind/pagefind.js', matcherUrl];
    pending = Promise.all(urls.map(url => import(/* @vite-ignore */ (url + retry))))
      .catch(error => {
        pending = undefined;
        failures++;
        throw error;
      });
  }
  return pending;
}
