import { useState, type FormEvent } from 'react';
import type { Platform, SearchRequest } from '../types';

export function SearchForm({ busy, maxPoints, onSubmit, recoveryRequest, recoveryStorageError, onResume, onDiscard, allowedPlatforms = ['bilibili', 'icourse163'] }: {
  busy: boolean; maxPoints: number; onSubmit: (request: SearchRequest) => Promise<void>;
  allowedPlatforms?: Platform[];
  recoveryRequest: SearchRequest | null; recoveryStorageError: string; onResume: () => void; onDiscard: () => void;
}) {
  const [knowledge, setKnowledge] = useState('');
  const [language, setLanguage] = useState<SearchRequest['language']>('zh');
  const [validation, setValidation] = useState('');
  const points = [...new Set(knowledge.split(/\r?\n/).map(value => value.trim()).filter(Boolean))];
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!points.length) { setValidation('请至少输入一个知识点。'); return; }
    if (points.length > maxPoints) { setValidation(`最多输入 ${maxPoints} 个知识点，请分批查找。`); return; }
    if (points.some(point => point.length > 160)) { setValidation('每个知识点请控制在 160 字以内。'); return; }
    setValidation('');
    void onSubmit({ knowledge_points: points, student_level: 'any', language, technical_version: '', project_context: '', preferred_platforms: allowedPlatforms.filter(platform => platform === 'bilibili' || platform === 'icourse163') });
  }
  return <aside className="form-panel panel">
    <h2>学习需求</h2>
    {recoveryRequest && <section className="recovery-notice" aria-label="未确认提交恢复">
      <strong>上次提交尚未确认</strong><p>知识点：{recoveryRequest.knowledge_points.join('、')}</p>
      <details><summary>查看原语言偏好</summary><p>语言：{{ zh: '中文', en: '英语', any: '不限' }[recoveryRequest.language]}</p></details>
      <p>继续将确认原任务，即使它已结束。恢复入口仅保存在本机当前标签页；提交不同需求会替换此入口。</p>
      {recoveryStorageError && <p role="alert">{recoveryStorageError}</p>}
      <div><button type="button" className="secondary-button" disabled={busy} onClick={onResume}>继续上次未确认提交</button><button type="button" className="text-button" disabled={busy} onClick={onDiscard}>清除此恢复入口</button></div>
      <p>清除入口不会取消可能已创建的任务。</p>
    </section>}
    <form onSubmit={submit}>
      <div className="field knowledge-field">
        <div className="label-line"><label htmlFor="knowledge">知识点</label><span>{points.length} / {maxPoints}</span></div>
        <textarea id="knowledge" rows={4} placeholder={`每行一个知识点，最多 ${maxPoints} 个`} value={knowledge} onChange={e => setKnowledge(e.target.value)} aria-describedby="knowledge-help" aria-invalid={!!validation} maxLength={1200} />
        <span id="knowledge-help" className="sr-only">每行输入一个知识点，重复行会自动合并。</span>
      </div>
      <div className="field"><label htmlFor="language">学习语言</label><select id="language" value={language} onChange={e => setLanguage(e.target.value as SearchRequest['language'])}><option value="zh">中文</option><option value="en">英语</option><option value="any">不限</option></select></div>
      {validation && <p className="form-error" role="alert">{validation}</p>}
      <button className="primary-button" type="submit" disabled={busy}>{busy ? '正在查找…' : '开始查找'}</button>
    </form>
  </aside>;
}
