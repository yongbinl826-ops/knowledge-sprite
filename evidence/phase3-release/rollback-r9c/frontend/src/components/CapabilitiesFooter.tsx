import { externalUrl } from '../api';
import type { Capabilities } from '../types';

export function CapabilitiesFooter({ capabilities, onRefresh }: { capabilities: Capabilities | null; onRefresh: () => void }) {
  return <footer className="capabilities-footer"><details><summary>来源与访问说明</summary><div className="capabilities-detail">
    <p>点击封面前往原平台。登录、选课与付费条件以原平台为准；章节推荐依据已取得的公开目录。</p>
    <div className="platform-capabilities">{capabilities?.platforms.filter(platform => platform.policy_basis).map(platform => <section key={platform.id}><h4>{platform.name}</h4><p>{platform.policy_basis}</p>{platform.source_url && externalUrl(platform.source_url) && <a href={externalUrl(platform.source_url)} target="_blank" rel="noopener noreferrer">查看平台条款{platform.policy_section ? `（${platform.policy_section}）` : ''}</a>}</section>)}</div>
    {!capabilities && <button className="text-button" onClick={onRefresh}>重新读取来源说明</button>}
  </div></details></footer>;
}
