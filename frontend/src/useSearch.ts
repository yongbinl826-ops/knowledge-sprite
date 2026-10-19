import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { openSnapshotStream } from './snapshotStream';
import { pendingRequest, readPendingCreation, savePendingCreation } from './pendingCreation';
import type { Capabilities, SearchJob, SearchRequest, SearchResults, JobCreated, JobCancelled } from './types';

const terminal = new Set(['completed', 'partial', 'failed', 'interrupted', 'cancelled']);
const resultsTerminal = (snapshot: SearchResults) => snapshot.pipeline?.terminal ?? terminal.has(snapshot.status);
export function useSearch() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState('');
  const [jobId, setJobId] = useState(() => new URLSearchParams(location.search).get('job') || '');
  const [job, setJob] = useState<SearchJob | null>(null);
  const [results, setResults] = useState<SearchResults | null>(null);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const [savedCreation, setSavedCreation] = useState(readPendingCreation);
  const [recoveryStorageError, setRecoveryStorageError] = useState('');
  const mounted = useRef(true);
  const submissionLock = useRef(false);
  const cancelLock = useRef(false);
  const pollController = useRef<AbortController | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const capabilityController = useRef<AbortController | null>(null);
  const pollGeneration = useRef(0);
  const pendingCreation = useRef(savedCreation);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      pollGeneration.current += 1;
      pollController.current?.abort(); actionController.current?.abort(); capabilityController.current?.abort();
    };
  }, []);

  const refreshCapabilities = useCallback(async () => {
    capabilityController.current?.abort();
    const controller = new AbortController();
    capabilityController.current = controller;
    try {
      const value = await api<Capabilities>('/api/capabilities', { signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      setCapabilities(value); setCapabilityError('');
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setCapabilityError((err as Error).message);
    }
  }, []);

  useEffect(() => { void refreshCapabilities(); }, [refreshCapabilities]);
  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    pollController.current = controller;
    const generation = ++pollGeneration.current;
    const current = () => mounted.current && !controller.signal.aborted && generation === pollGeneration.current;
    let timer = 0;
    let failures = 0;
    let allowStream = true;
    let closeStream = () => {};
    const applySnapshot = (snapshot: SearchResults) => {
      if (!current()) return;
      if (snapshot.job_id !== jobId || !snapshot.job || snapshot.job.job_id !== jobId || snapshot.job.status !== snapshot.status) throw new Error('返回的任务状态不一致，未替换当前结果。');
      setJob(snapshot.job); setResults(snapshot); setPollError(''); failures = 0;
      if (resultsTerminal(snapshot)) { closeStream(); void refreshCapabilities(); }
    };
    const poll = async () => {
      if (!current()) return;
      const round = new AbortController();
      const abortRound = () => round.abort();
      controller.signal.addEventListener('abort', abortRound, { once: true });
      try {
        const [nextJob, nextResults] = await Promise.all([
          api<SearchJob>(`/api/search-jobs/${encodeURIComponent(jobId)}`, { signal: round.signal }),
          api<SearchResults>(`/api/search-jobs/${encodeURIComponent(jobId)}/results`, { signal: round.signal }),
        ]);
        if (!current()) return;
        // A terminal transition can occur between the two independent reads.
        const coherentResults = terminal.has(nextJob.status) && nextResults.status !== nextJob.status
          ? await api<SearchResults>(`/api/search-jobs/${encodeURIComponent(jobId)}/results`, { signal: round.signal })
          : nextResults;
        if (!current()) return;
        if (nextJob.job_id !== jobId || coherentResults.job_id !== jobId) throw new Error('返回的任务编号不一致，未替换当前结果。');
        setJob(nextJob); setResults(coherentResults); setPollError(''); failures = 0;
        if (coherentResults.pipeline?.terminal ?? terminal.has(nextJob.status)) { void refreshCapabilities(); return; }
        if (allowStream && coherentResults.pipeline) {
          allowStream = false;
          closeStream = openSnapshotStream<SearchResults>({
            url: `/api/search-jobs/${encodeURIComponent(jobId)}/events`, signal: controller.signal,
            onSnapshot: applySnapshot,
            onComplete: snapshot => { if (!snapshot || !resultsTerminal(snapshot)) throw new Error('缺少最终任务状态'); applySnapshot(snapshot); },
            onFallback: () => { if (current()) void poll(); },
          });
          return;
        }
      } catch (err) {
        if (!current()) return;
        failures += 1;
        setPollError(`进度暂时无法读取：${(err as Error).message}${failures < 3 ? ' 正在重试。' : ' 已暂停轮询，可手动重试。'}`);
        if (failures >= 3) return;
      } finally {
        // A failed Promise.all must also stop its still-pending sibling request.
        round.abort(); controller.signal.removeEventListener('abort', abortRound);
      }
      if (current()) timer = window.setTimeout(poll, 1500);
    };
    void poll();
    return () => { controller.abort(); closeStream(); window.clearTimeout(timer); };
  }, [jobId, pollRevision, refreshCapabilities]);

  const stopPolling = () => { pollGeneration.current += 1; pollController.current?.abort(); };
  const submit = async (request: SearchRequest) => {
    if (submissionLock.current || cancelLock.current) return;
    submissionLock.current = true;
    const controller = new AbortController();
    actionController.current = controller;
    stopPolling(); setSubmitting(true); setError(''); setPollError(''); setNotice('');
    const body = JSON.stringify(request);
    if (pendingCreation.current?.body !== body) pendingCreation.current = { body, key: crypto.randomUUID() };
    setSavedCreation(pendingCreation.current);
    setRecoveryStorageError(savePendingCreation(pendingCreation.current) ? '' : '浏览器未允许保存恢复标识；本页可继续重试，但刷新后无法恢复这次未确认提交。');
    try {
      const created = await api<JobCreated>('/api/search-jobs', { method: 'POST', headers: { 'Idempotency-Key': pendingCreation.current.key }, body, signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      if (!created.job_id || typeof created.job_id !== 'string') throw new Error('未收到有效任务编号；可继续上次提交以确认任务。');
      pendingCreation.current = null;
      savePendingCreation(null); setSavedCreation(null); setRecoveryStorageError('');
      setJob(null); setResults(null); setJobId(created.job_id);
      setNotice(created.reused ? '已返回相同需求的原任务，未重复发起搜索。' : '');
      // The server may return the same job ID; refresh even when that ID is unchanged.
      setPollRevision(value => value + 1);
      const url = new URL(location.href); url.searchParams.set('job', created.job_id);
      history.replaceState(null, '', url);
    } catch (err) {
      if (!mounted.current || controller.signal.aborted) return;
      const uncertain = err instanceof ApiError && ['timeout', 'network'].includes(err.code);
      setError((err as Error).message + (uncertain ? ' 创建状态尚未确认；重新提交相同需求会沿用本次提交标识，避免重复创建。' : ''));
      setPollRevision(value => value + 1);
    } finally {
      submissionLock.current = false;
      if (mounted.current) setSubmitting(false);
    }
  };
  const discardPending = () => {
    if (submissionLock.current || cancelLock.current) return;
    pendingCreation.current = null; savePendingCreation(null); setSavedCreation(null); setRecoveryStorageError('');
  };

  const cancel = async () => {
    if (!jobId || cancelLock.current || submissionLock.current || (results?.pipeline?.terminal ?? (job && terminal.has(job.status)))) return;
    cancelLock.current = true;
    const controller = new AbortController();
    actionController.current = controller;
    stopPolling(); setCancelling(true); setError(''); setPollError('');
    try {
      const cancelled = await api<JobCancelled>(`/api/search-jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      setNotice(cancelled.cancelled ? '取消已确认，已获取的结果和来源证据仍可查看。' : '任务已结束，已保留原任务状态。');
      setJob(current => current?.job_id === cancelled.job_id ? { ...current, status: cancelled.status, phase: terminal.has(cancelled.status) ? 'done' : current.phase } : current);
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError(`取消状态尚未确认：${(err as Error).message} 将重新读取任务状态。`);
    } finally {
      cancelLock.current = false;
      if (mounted.current) { setCancelling(false); setPollRevision(value => value + 1); }
    }
  };
  return { capabilities, capabilityError, jobId, job, results, error: error || pollError, notice, submitting, cancelling, submit, cancel,
    recoveryRequest: pendingRequest(savedCreation), recoveryStorageError, discardPending,
    resumePending: () => { const request = pendingRequest(pendingCreation.current); if (request) return submit(request); },
    canCancel: !!jobId && !submitting && !(results?.pipeline?.terminal ?? (job && terminal.has(job.status))),
    busy: submitting || cancelling || (!!jobId && !job && !error && !pollError) || (results?.pipeline ? !results.pipeline.terminal : !!job && !terminal.has(job.status)),
    refreshCapabilities, retryPoll: () => { setError(''); setPollError(''); setPollRevision(value => value + 1); } };
}
