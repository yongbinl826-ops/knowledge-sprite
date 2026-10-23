import { useEffect, useRef, useState } from 'react';
import { App as NativeApp } from '@capacitor/app';
import type { PluginListenerHandle } from '@capacitor/core';
import { ProjectFlowView } from '../components/ProjectFlow';
import { SearchForm } from '../components/SearchForm';
import type { Capabilities } from '../types';
import { deviceStore, nativeDevice, deviceStorageLabel } from './deviceRuntime';
import { mobileApiBase, MobileApi, deviceDevelopment } from './mobileApi';
import { LocalProjectService } from './localProjectService';
import { useDeviceProject } from './useDeviceProject';
import { installDeviceLinks } from './deviceLinks';
import './device.css';

export function DeviceApp() {
  const [setup] = useState(() => {
    let base = '', error = '';
    try { base = mobileApiBase(import.meta.env.VITE_API_BASE_URL, deviceDevelopment(import.meta.env.DEV, import.meta.env.VITE_MOBILE_DEBUG_LOOPBACK), location.origin); }
    catch { error = '尚未配置安全的设备服务地址。可离线查看已有记录；新分析和检索暂不可用。'; }
    const api = new MobileApi(base); return { api, error, service: new LocalProjectService(deviceStore, api) };
  });
  const project = useDeviceProject(setup.service, setup.error);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null), [capabilityError, setCapabilityError] = useState('');
  const [manual, setManual] = useState(false), [linkError, setLinkError] = useState('');
  const overlay = useRef<HTMLElement | null>(null), returnFocus = useRef<HTMLElement | null>(null);
  const openManual = () => { returnFocus.current = document.activeElement as HTMLElement; setManual(true); };
  const closeOverlay = () => { setManual(false); requestAnimationFrame(() => returnFocus.current?.focus()); };
  useEffect(() => {
    if (setup.error) return;
    const controller = new AbortController();
    void setup.api.capabilities(controller.signal).then(value => { setCapabilities(value); setCapabilityError(''); })
      .catch(() => { if (!controller.signal.aborted) setCapabilityError('服务状态暂不可读取；本机记录仍可离线查看。'); });
    return () => controller.abort();
  }, [setup]);
  useEffect(() => installDeviceLinks(setLinkError), []);
  useEffect(() => {
    if (!nativeDevice()) return;
    let disposed = false; const handles: PluginListenerHandle[] = [];
    const retain = (handle: PluginListenerHandle) => { if (disposed) void handle.remove(); else handles.push(handle); };
    void NativeApp.addListener('appStateChange', state => { if (state.isActive) window.dispatchEvent(new Event('device-resume')); }).then(retain);
    void NativeApp.addListener('backButton', () => {
      if (manual) { closeOverlay(); return; }
      const event = new Event('device-back', { cancelable: true });
      if (document.dispatchEvent(event)) void NativeApp.minimizeApp();
    }).then(retain);
    return () => { disposed = true; handles.forEach(handle => { void handle.remove(); }); };
  }, [manual]);
  useEffect(() => {
    if (!manual) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeOverlay(); return; }
      if (event.key !== 'Tab') return;
      const controls = [...(overlay.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],textarea:not([disabled])') || [])];
      if (!controls.length) return;
      const first = controls[0], last = controls.at(-1)!;
      if (event.shiftKey && (document.activeElement === first || !overlay.current?.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key);
  }, [manual]);
  return <div className="device-app">
    <div inert={manual}>
      {setup.error && <p className="device-global-notice notice warning-notice" role="status">{setup.error}</p>}
      {linkError && <p className="device-global-notice notice error-notice" role="alert">{linkError}<button className="text-button" onClick={() => setLinkError('')}>关闭提示</button></p>}
      <ProjectFlowView capabilities={capabilities} capabilityError={capabilityError} project={project} device={project}
        onManual={openManual} storageNotice={deviceStorageLabel()}/>
    </div>
    {manual && <section className="device-overlay" ref={overlay}>
      <section className="device-library" role="dialog" aria-modal="true" aria-label="直接检索专业知识点">
        <div className="device-library-heading"><h2 tabIndex={-1} ref={node => node?.focus()}>直接检索知识点</h2><button className="text-button" onClick={closeOverlay}>返回项目</button></div>
        <p>明确点击后才提交临时检索任务；结果作为本机项目保存。</p>
        <SearchForm allowedPlatforms={['bilibili', 'icourse163']} recoveryRequest={null} recoveryStorageError="" onResume={() => {}} onDiscard={() => {}} busy={project.busy} maxPoints={capabilities?.limits.max_knowledge_points || 5} onSubmit={async request => { const result = await project.directSearch(request); if (result) closeOverlay(); }}/>
        {project.error && <p className="notice error-notice" role="alert">{project.error}</p>}
      </section>
    </section>}
  </div>;
}
