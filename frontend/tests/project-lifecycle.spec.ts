import {test,expect,type Page} from '@playwright/test';
import type {ProjectView} from '../src/projectTypes';
// Isolated transport only: no actual analysis, search, platform request or playback.
const stamp='2026-10-19T06:10:00Z',input={name:'专业知识点检索',requirements:'离线验证恢复入口和封面状态。',student_level:'beginner',language:'zh',project_context:'',technical_version:'',preferred_platforms:['bilibili','icourse163']};
function fixture(status='running'):ProjectView{
 const names=['pygame 事件循环','矩形碰撞检测','有限状态机'];
 const points=names.map((name,i)=>({id:`k${i+1}`,name,description:'历史描述',function_ids:['f1'],why_needed:'历史关联',learning_goal:'历史目标',necessity:'required',prerequisite_ids:[],learning_order:i+1,selection:'learn'}));
 const resource={resource_id:'partial-source',title:'实际局部材料的离线展示控制',url:'https://www.bilibili.com/video/BV164411J7GE/',canonical_url:'https://www.bilibili.com/video/BV164411J7GE/',platform:'bilibili',resource_type:'video',thumbnail_url:null};
 return {project_id:'lifecycle-project',input,current_version:1,versions:[{version:1,status,created_at:stamp}],version:{version:1,status,input,analysis:{scope:'离线控制',technical_plan:'历史方案',assumptions:[],functions:[{id:'f1',name:'原功能',original_requirement:'原需求',acceptance_criteria:'原验收'}],knowledge_points:points},confirmation:{version:1,confirmed_at:stamp,acknowledged_skipped_prerequisites:['old-ack-must-not-be-invented']},batches:[{batch_id:'b1',status:status==='running'?'submitted':'completed',job_status:status==='running'?'running':status,project_knowledge_point_ids:['k1','k2','k3'],job_id:'original-job'}],error:status==='failed'?{message:'离线控制：搜索服务暂时不可用',code:'source_unavailable'}:null,created_at:stamp},points:points.map((p,i)=>({project_knowledge_point_id:p.id,name:p.name,selection:'learn',status:status==='running'?(i===0?'no_results':i===1?'queued':'partial'):status==='failed'?'failed':'no_results',batch_id:'b1',job_id:'original-job',knowledge_point_id:p.id,result:i===2?{knowledge_point_id:p.id,text:p.name,items:[],partial_items:[],discovery_items:[{resource,discovery_evidence:[]}],total_matches:0}:null}))} as unknown as ProjectView;
}
async function setup(page:Page,initial=fixture(),failCancelOnce=false){
 const versions=new Map([[1,structuredClone(initial)]]);let latest=1,cancelFailures=failCancelOnce?1:0;
 const writes:{action:string,body:any}[]=[],unexpected:string[]=[],runtime:string[]=[],errors:string[]=[];page.on('pageerror',e=>runtime.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});await page.emulateMedia({reducedMotion:'reduce'});
 const current=(version=latest)=>({...structuredClone(versions.get(version)!),current_version:latest,versions:[...versions.values()].map(v=>({version:v.version!.version,status:v.version!.status,created_at:stamp}))});
 const origin=new URL(process.env.PLAYWRIGHT_BASE_URL!).origin;
 await page.route('**/*',async route=>{const r=route.request(),url=new URL(r.url());if(url.origin!==origin){unexpected.push(url.href);return route.abort();}if(!url.pathname.startsWith('/api/'))return route.continue();
 if(r.method()==='GET'){
  if(url.pathname==='/api/capabilities')return route.fulfill({json:{mode:'live',teaching_match_enabled:false,search:{status:'configured',selected_provider:'fixture',message:'offline',providers:[]},llm:{status:'unconfigured',message:'offline'},fetch:{status:'available',message:'offline',browser_fallback:false},platforms:[],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40}}});
  if(url.pathname==='/api/projects')return route.fulfill({json:{projects:[{project_id:'lifecycle-project',name:input.name,current_version:latest,created_at:stamp,updated_at:stamp}]}});
  if(url.pathname==='/api/projects/lifecycle-project/results')return route.fulfill({json:current(Number(url.searchParams.get('version'))||latest)});
 }
 if(r.method()==='POST'&&url.pathname.startsWith('/api/projects/lifecycle-project/')){
  const action=url.pathname.split('/').at(-1)!,body=r.postDataJSON();writes.push({action,body});
  if(action==='cancel'){
   if(cancelFailures-- >0)return route.fulfill({status:503,json:{detail:'取消尚未确认，请稍后重试'}});
   const v=versions.get(body.version)!;v.version!.status='cancelled';for(const b of v.version!.batches){b.status='cancelled';b.job_status='cancelled';}for(const p of v.points!)if(p.status==='queued')p.status='cancelled';
  }else if(action==='edit'){
   expect(body.expected_version).toBe(latest);const v=current();latest++;v.current_version=latest;v.version={...v.version!,version:latest,status:'analyzed',analysis:body.analysis,confirmation:null,batches:[],error:null};v.points=[];versions.set(latest,v);
  }else if(action==='confirm'){
   expect(body.version).toBe(latest);const v=versions.get(latest)!;v.version!.status='confirmed';v.version!.confirmation={version:latest,confirmed_at:stamp,acknowledged_skipped_prerequisites:body.acknowledged_skipped_prerequisites};
  }else if(action==='search'){
   expect(body.version).toBe(latest);const v=versions.get(latest)!;v.version!.status='completed';v.points=structuredClone(initial.points);for(const p of v.points!)p.status=p.result?'partial':'no_results';
  }else{unexpected.push(url.pathname);return route.abort();}
  return route.fulfill({json:current()});
 }
 unexpected.push(`${r.method()} ${url.pathname}`);return route.abort();});
 await page.goto('/?project=lifecycle-project&version=1');await expect(page.getByRole('region',{name:'视频封面',exact:true})).toBeVisible();
 return {writes,current,versions,clean:()=>{expect(unexpected).toEqual([]);expect(runtime).toEqual([]);expect(errors).toEqual(failCancelOnce?['Failed to load resource: the server responded with a status of 503 (Service Unavailable)']:[]);}};
}
const pane=(page:Page)=>page.locator('.stage-content');
const nav=(page:Page)=>page.getByRole('navigation',{name:'已选知识点'});
test('r3 已结束空知识点不借项目全局running等待，排队点仍加载、已有局部封面可打开',async({page})=>{
 const s=await setup(page);await nav(page).getByRole('button',{name:'pygame 事件循环',exact:true}).click();await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(page.getByRole('status',{name:'正在读取视频封面'})).toHaveCount(0);
 await nav(page).getByRole('button',{name:'矩形碰撞检测',exact:true}).click();await expect(page.getByRole('status',{name:'正在读取视频封面'})).toBeVisible();
 await nav(page).getByRole('button',{name:'有限状态机',exact:true}).click();await expect(pane(page).getByRole('link')).toHaveAttribute('href','https://www.bilibili.com/video/BV164411J7GE/');expect(await pane(page).innerText()).toBe('');expect(s.writes).toEqual([]);s.clean();
});
test('r3 左侧取消失败不假报成功；显式取消后保留封面，重新检索只建一个新版本且不继承旧ack',async({page})=>{
 const s=await setup(page,fixture(),true);await page.getByRole('button',{name:'取消项目检索',exact:true}).click();await expect(page.getByRole('alert')).toContainText('取消尚未确认');expect(s.current().version!.status).toBe('running');await expect(page.getByRole('button',{name:'取消项目检索',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'取消项目检索',exact:true}).click();await expect(page.locator('.stage-intro')).toContainText('已取消');await expect(pane(page).getByRole('link')).toHaveCount(1);await expect(page.getByRole('button',{name:'取消项目检索',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'重新检索这些知识点',exact:true}).click();await expect(page.locator('.stage-intro')).toContainText('检索完成');expect(s.writes.map(w=>w.action)).toEqual(['cancel','cancel','edit','confirm','search']);expect(s.writes[3].body).toEqual({version:2,acknowledged_skipped_prerequisites:[]});expect(s.versions.get(1)!.version!.batches[0].job_id).toBe('original-job');expect(s.versions.get(1)!.version!.status).toBe('cancelled');expect(await pane(page).innerText()).toBe('');s.clean();
});
test('r3 失败或空结果可从左侧键盘重试；历史只读；三宽右侧无文字和溢出',async({page},info)=>{
 const s=await setup(page,fixture('failed'));await expect(page.locator('.stage-intro').getByRole('alert')).toContainText('搜索服务暂时不可用');await expect(page.getByRole('status',{name:'正在读取视频封面'})).toHaveCount(0);
 for(const size of[{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){await page.setViewportSize(size);expect(await pane(page).innerText()).toBe('');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);await page.screenshot({path:info.outputPath(`failed-left-recovery-${size.name}.png`),animations:'disabled'});}
 await page.getByRole('button',{name:'重新检索这些知识点',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.locator('.stage-intro')).toContainText('检索完成');expect(s.writes.map(w=>w.action)).toEqual(['edit','confirm','search']);
 await page.getByRole('button',{name:'我的项目'}).click();await page.getByLabel('查看版本',{exact:true}).selectOption('1');await expect(page.locator('.stage-intro').getByRole('alert')).toContainText('搜索服务暂时不可用');await expect(page.getByRole('button',{name:'重新检索这些知识点',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'取消项目检索',exact:true})).toHaveCount(0);expect(s.writes).toHaveLength(3);s.clean();
});
