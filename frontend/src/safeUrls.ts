export function externalUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (!host.includes('.') || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal') || host.includes(':') || host.startsWith('[')) return undefined;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b] = host.split('.').map(Number);
      if (a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127)) return undefined;
    }
    return url.href;
  } catch { return undefined; }
}

export function courseImageUrl(value: string | null | undefined): string | undefined {
  const safe = value ? externalUrl(value) : undefined;
  if (!safe) return undefined;
  const url = new URL(safe);
  if (url.protocol === 'http:' && /^i\d+\.hdslb\.com$/i.test(url.hostname) && !url.port) url.protocol = 'https:';
  return url.protocol === 'https:' ? url.href : undefined;
}
