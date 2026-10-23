import { Browser } from '@capacitor/browser';
import { nativeDevice } from './deviceRuntime';
import { externalUrl } from '../safeUrls';

export function installDeviceLinks(onError: (message: string) => void): () => void {
  const click = (event: MouseEvent) => {
    const anchor = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[href]');
    if (!anchor || !nativeDevice() || !/^https?:/i.test(anchor.getAttribute('href') || '')) return;
    event.preventDefault(); event.stopPropagation();
    const safe = externalUrl(anchor.href);
    if (!safe || new URL(safe).protocol !== 'https:') { onError('该外链未通过安全校验，未打开。'); return; }
    void Browser.open({ url: safe }).catch(() => onError('系统浏览器暂时无法打开，请稍后再试。'));
  };
  document.addEventListener('click', click, true);
  return () => document.removeEventListener('click', click, true);
}
