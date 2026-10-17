import React from 'react';
import { createRoot } from 'react-dom/client';
import { ResourceCard } from '../../../frontend/src/components/ResourceCard';
import '../../../frontend/src/styles.css';
import results from '../extraction-comparison.json';

function Audit() {
  return <main style={{ maxWidth: 1080, margin: '32px auto', padding: 24 }}>
    <h1>B站与 MOOC 真实目录核验</h1>
    <p>2026-10-17 · 真实平台页面观察与目录提取复核</p>
    <p role="note">这里展示已保存的真实页面证据，复用应用正式资源卡片。没有发起新的全网搜索，也不表示后台自动采集已打通。</p>
    <p>B站：15个分P。MOOC：9章、57课时、2个补充视频教程、9个测验、7项作业，共84项。</p>
    <p>条目直链未知；页面给出的时长按原值保留。MOOC当前学期已关闭。播放核验与目录核验分别判断。</p>
    <div style={{ display: 'grid', gap: 24, marginTop: 24 }}>
      {results.ui_items.map(item => <ResourceCard key={item.resource.resource_id} item={item} points={[results.point]} placement={item.match.topic_evidence_status}/>) }
    </div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Audit/>);
