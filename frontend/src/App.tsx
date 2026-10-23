import { useState } from 'react';
import { BookIcon } from './components/Icons';
import { SearchForm } from './components/SearchForm';
import { ResultsPanel } from './components/ResultsPanel';
import { CapabilitiesFooter } from './components/CapabilitiesFooter';
import { ProjectFlow } from './components/ProjectFlow';
import { useSearch } from './useSearch';
import { deviceMode } from './device/deviceRuntime';
import { DeviceApp } from './device/DeviceApp';

function LegacyApp() {
  const search = useSearch();
  const [mode, setMode] = useState<'manual' | 'project'>(() => {
    const query = new URLSearchParams(location.search);
    return query.has('job') || query.get('mode') === 'manual' ? 'manual' : 'project';
  });
  const switchMode = (next: 'manual' | 'project') => {
    setMode(next);
    const url = new URL(location.href);
    if (next === 'manual') {
      url.searchParams.set('mode', 'manual');
      url.searchParams.delete('project'); url.searchParams.delete('version');
    } else { url.searchParams.delete('mode'); url.searchParams.delete('job'); }
    history.replaceState(null, '', url);
  };
  if (mode === 'project') return <ProjectFlow capabilities={search.capabilities} capabilityError={search.capabilityError} onManual={() => switchMode('manual')}/>;
  return <>
    <a className="skip-link" href="#knowledge">跳转到知识点输入</a>
    <header className="site-header"><div className="brand"><BookIcon/><span>项目制学习引导小精灵</span></div><button className="text-button" onClick={() => switchMode('project')}>从项目开始 <span aria-hidden="true">↗</span></button></header>
    <main className="manual-main"><div className="intro"><p className="section-index">DIRECT / LEARNING</p><h1>想学的知识，<br/>从这里开始。</h1><p>输入具体知识点，找到相关视频与有证据的学习章节。</p></div>
      <div className="workspace"><SearchForm busy={search.busy} maxPoints={search.capabilities?.limits.max_knowledge_points || 5} onSubmit={search.submit} recoveryRequest={search.recoveryRequest} recoveryStorageError={search.recoveryStorageError} onResume={() => void search.resumePending()} onDiscard={search.discardPending}/><ResultsPanel capabilities={search.capabilities} capabilityError={search.capabilityError} job={search.job} results={search.results} jobId={search.jobId} error={search.error} notice={search.notice} canCancel={search.canCancel} cancelling={search.cancelling} onCancel={() => void search.cancel()} onRetry={search.retryPoll} onRefresh={() => void search.refreshCapabilities()}/></div>
      <CapabilitiesFooter capabilities={search.capabilities} onRefresh={() => void search.refreshCapabilities()}/>
    </main>
  </>;
}

export default function App() { return deviceMode ? <DeviceApp/> : <LegacyApp/>; }
