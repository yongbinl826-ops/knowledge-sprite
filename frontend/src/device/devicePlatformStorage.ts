import { DeviceStorageError, type KeyValueStorage } from './deviceStorage.ts';

export type DurableBridge = { get(options: { key: string }): Promise<{ value: string | null }>;
  set(options: { key: string; value: string }): Promise<{ committed: boolean }> };

/** Android commit acknowledgement is required before any task POST. Preferences
 * apply()/web cache is deliberately not used as a native durability fallback. */
export function devicePlatformStorage(platform: () => string, bridge: DurableBridge, web: () => Storage): KeyValueStorage {
  const requireAndroid = () => {
    if (platform() !== 'android') throw new DeviceStorageError('此原生平台尚未接入可靠的本机存储，未创建任务。请使用已验证的 Android 版本。');
  };
  return {
    async get(key) {
      if (platform() === 'web') return web().getItem(key);
      requireAndroid();
      try { const result = await bridge.get({ key });
        if (result.value !== null && typeof result.value !== 'string') throw new Error('invalid bridge read');
        return result.value;
      } catch { throw new DeviceStorageError('无法可靠读取本机记录；原记录未删除，请稍后重新读取。'); }
    },
    async set(key, value) {
      if (platform() === 'web') { web().setItem(key, value); return; }
      requireAndroid();
      try { const result = await bridge.set({ key, value }); if (result.committed !== true) throw new Error('native commit not acknowledged'); }
      catch { throw new DeviceStorageError('设备未确认可靠落盘；旧记录保留，未继续提交任务。请检查存储空间后重试。'); }
    },
  };
}
