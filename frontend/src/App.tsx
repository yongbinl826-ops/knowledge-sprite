import { BookIcon } from './components/Icons';
import { SearchForm } from './components/SearchForm';
import { ResultsPanel } from './components/ResultsPanel';
import { CapabilitiesFooter } from './components/CapabilitiesFooter';
import { useSearch } from './useSearch';

export default function App() {
  const search = useSearch();
  return <><a className="skip-link" href="#knowledge">跳转到知识点输入</a><header className="site-header"><div className="brand"><BookIcon/><span>项目制知识引导小精灵</span></div><span className="header-description">课程与视频发现</span></header>
    <main><div className="intro"><h1>想学的知识，去哪里学？</h1><p>输入知识点，找到课程与对应章节。</p></div><div className="workspace"><SearchForm busy={search.busy} maxPoints={search.capabilities?.limits.max_knowledge_points || 5} onSubmit={search.submit} recoveryRequest={search.recoveryRequest} recoveryStorageError={search.recoveryStorageError} onResume={() => void search.resumePending()} onDiscard={search.discardPending}/><ResultsPanel capabilities={search.capabilities} capabilityError={search.capabilityError} job={search.job} results={search.results} jobId={search.jobId} error={search.error} notice={search.notice} canCancel={search.canCancel} cancelling={search.cancelling} onCancel={() => void search.cancel()} onRetry={search.retryPoll} onRefresh={() => void search.refreshCapabilities()}/></div><CapabilitiesFooter capabilities={search.capabilities} onRefresh={() => void search.refreshCapabilities()}/></main></>;
}
