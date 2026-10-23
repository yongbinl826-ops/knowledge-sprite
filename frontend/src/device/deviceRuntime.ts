import { Capacitor, registerPlugin } from '@capacitor/core';
import { DeviceStore } from './deviceStorage';
import { devicePlatformStorage, type DurableBridge } from './devicePlatformStorage';

export const deviceMode = import.meta.env.VITE_DEVICE_MODE === 'true';
export const nativeDevice = () => Capacitor.isNativePlatform();
const bridge = registerPlugin<DurableBridge>('DurableDeviceStore');
const storage = devicePlatformStorage(() => nativeDevice() ? Capacitor.getPlatform() : 'web', bridge, () => localStorage);
export const deviceStore = new DeviceStore(storage);
export const deviceStorageLabel = () => nativeDevice() ? '仅保存在这台设备' : '网页测试：仅保存在此浏览器';
