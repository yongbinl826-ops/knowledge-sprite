import { useState, type FormEvent } from 'react';
import { platformNames } from '../api';
import type { Platform, SearchRequest } from '../types';

export function SearchForm({ busy, maxPoints, onSubmit, recoveryRequest, recoveryStorageError, onResume, onDiscard }: {
  busy: boolean; maxPoints: number; onSubmit: (request: SearchRequest) => Promise<void>;
  recoveryRequest: SearchRequest | null; recoveryStorageError: string; onResume: () => void; onDiscard: () => void;
}) {
  const [knowledge, setKnowledge] = useState('');
  const [level, setLevel] = useState<SearchRequest['student_level']>('beginner');
  const [language, setLanguage] = useState<SearchRequest['language']>('zh');
  const [version, setVersion] = useState('');
  const [context, setContext] = useState('');
  const [platforms, setPlatforms] = useState<Platform[]>(['bilibili', 'icourse163', 'xuetangx']);
  const [validation, setValidation] = useState('');
  const points = [...new Set(knowledge.split(/\r?\n/).map(value => value.trim()).filter(Boolean))];
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!points.length) { setValidation('请至少输入一个知识点。'); return; }
    if (points.length > maxPoints) { setValidation(`最多输入 ${maxPoints} 个知识点，请分批查找。`); return; }
    if (points.some(point => point.length > 160)) { setValidation('每个知识点请控制在 160 字以内。'); return; }
    setValidation('');
    void onSubmit({ knowledge_points: points, student_level: level, language, technical_version: version.trim(), project_context: context.trim(), preferred_platforms: platforms });
  }
  return <aside className="form-panel panel">
    <h2>学习需求</h2>
    {recoveryRequest && <section className="recovery-notice" aria-label="未确认提交恢复">
      <strong>上次提交尚未确认</strong><p>知识点：{recoveryRequest.knowledge_points.join('、')}</p>
      <details><summary>查看原学习需求</summary><p>学生基础：{{ beginner: '初学者', intermediate: '有一定基础', advanced: '进阶学习', any: '不限' }[recoveryRequest.student_level]}；语言：{{ zh: '中文', en: '英语', any: '不限' }[recoveryRequest.language]}</p><p>技术版本：{recoveryRequest.technical_version || '未填写'}；项目背景：{recoveryRequest.project_context || '未填写'}</p><p>优先平台：{recoveryRequest.preferred_platforms.map(platform => platformNames[platform]).join('、') || '未指定'}</p></details>
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
      <div className="field-pair">
        <div className="field"><label htmlFor="level">学生基础</label><select id="level" value={level} onChange={e => setLevel(e.target.value as SearchRequest['student_level'])}><option value="beginner">初学者</option><option value="intermediate">有一定基础</option><option value="advanced">进阶学习</option><option value="any">不限</option></select></div>
        <div className="field"><label htmlFor="language">学习语言</label><select id="language" value={language} onChange={e => setLanguage(e.target.value as SearchRequest['language'])}><option value="zh">中文</option><option value="en">英语</option><option value="any">不限</option></select></div>
      </div>
      <details className="search-options"><summary>更多筛选</summary><div className="search-options-content">
      <div className="field"><label htmlFor="version">技术版本 <span>（可选）</span></label><input id="version" value={version} onChange={e => setVersion(e.target.value)} placeholder="例如：Python 3.11、Vue 3、JDK 17" maxLength={100}/></div>
      <div className="field"><label htmlFor="context">项目背景 <span>（可选）</span></label><input id="context" value={context} onChange={e => setContext(e.target.value)} placeholder="例如：做一个博客系统、课程设计" maxLength={1000}/></div>
      <fieldset className="platform-choices"><legend>优先搜索的平台</legend><div>{(['bilibili', 'icourse163', 'xuetangx'] as Platform[]).map(platform => <label key={platform} className={`platform-choice ${platforms.includes(platform) ? 'selected' : ''}`}><input type="checkbox" checked={platforms.includes(platform)} onChange={() => setPlatforms(current => current.includes(platform) ? current.filter(value => value !== platform) : [...current, platform])}/><span>{platformNames[platform]}</span></label>)}</div><p>也会搜索其他公开课程网站</p></fieldset>
      </div></details>
      {validation && <p className="form-error" role="alert">{validation}</p>}
      <button className="primary-button" type="submit" disabled={busy}>{busy ? '正在查找…' : '开始查找'}</button>
    </form>
  </aside>;
}
