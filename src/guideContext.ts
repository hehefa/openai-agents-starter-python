const officialOrigins = new Set([
  'https://hefa.p4theater.cn',
  'https://p4theater.cn',
  'https://p.p4theater.cn',
]);
const localHosts = new Set(['localhost', '127.0.0.1']);

export function guideCollection(search: string): 'classic' | undefined {
  const query = new URLSearchParams(search);
  return query.get('site') === 'p4' && query.get('collection') === 'classic' ? 'classic' : undefined;
}

export function guideStorageKey(collection?: 'classic'): string {
  return 'works-guide-session-v1' + (collection ? ':classic' : '');
}

export function readableSourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    if (officialOrigins.has(url.origin) && !url.username && !url.password) return url.href;
  } catch { /* Invalid source URLs remain plain text. */ }
  return undefined;
}

export function guideParentOrigin(referrer: string, currentHost: string): string | undefined {
  try {
    const url = new URL(referrer);
    if (officialOrigins.has(url.origin) || (localHosts.has(currentHost) && localHosts.has(url.hostname))) return url.origin;
  } catch { /* A missing referrer cannot authorize a parent. */ }
  return undefined;
}
