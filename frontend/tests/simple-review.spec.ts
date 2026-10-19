import {expect,test,type Page} from '@playwright/test';
import type {ProjectAnalysis,ProjectView} from '../src/projectTypes';

// Offline compatibility controls, not evidence of real generated professional terms.
const input={name:'Python 小游戏',requirements:'方向键移动、碰撞检测、计分与重新开始。',student_level:'beginner',language:'zh',technical_version:'Python',project_context:'',preferred_platforms:['bilibili','icourse163']};
function fixture():ProjectView {
  const point=(id:string,name:string,order:number,selection:string,prerequisite_ids:string[])=>({id,name,description:`旧描述 ${id}`,function_ids:['f1'],why_needed:'旧关联原样保留',learning_goal:'旧目标原样保留',necessity:'required',prerequisite_ids,learning_order:order,selection,technology:'pygame',project_task:'隐藏历史任务',concepts:['隐藏历史概念'],learning_skills:['隐藏历史技能'],practice_check:'隐藏历史练习',custom_extension:{unchanged:true}});
  return {project_id:'simple-review',input,current_version:1,versions:[{version:1,status:'analyzed',created_at:'2026-10-19T05:45:00Z'}],version:{version:1,status:'analyzed',created_at:'2026-10-19T05:45:00Z',input,analysis:{scope:'历史范围',technical_plan:'旧方案原样保留',assumptions:['旧假设'],functions:[{id:'f1',name:'原功能',original_requirement:'原始需求',acceptance_criteria:'原验收'}],learner_profile:{prior_knowledge:['历史起点']},knowledge_points:[point('k1','pygame 事件循环',1,'learn',[]),point('k2','矩形碰撞检测',2,'learn',['k1']),point('k3','状态机',3,'mastered',['k2'])]},confirmation:null,batches:[],error:null},points:[]} as unknown as ProjectView;
}
async function setup(page:Page,initial=fixture()) {
  let current=structuredClone(initial);
  const writes:{action:string,body:any}[]=[],unexpected:string[]=[],runtime:string[]=[],consoleErrors:string[]=[];
  page.on('pageerror',e=>runtime.push(e.message));page.on('console',m=>{if(['warning','error'].includes(m.type()))consoleErrors.push(m.text());});
  await page.emulateMedia({reducedMotion:'reduce'});
  const origin=new URL(process.env.PLAYWRIGHT_BASE_URL!).origin;
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.origin!==origin){unexpected.push(url.href);return route.abort();}
    if(!url.pathname.startsWith('/api/'))return route.continue();
    if(request.method()==='GET'){
      if(url.pathname==='/api/capabilities')return route.fulfill({json:{mode:'live',teaching_match_enabled:false,search:{status:'configured',selected_provider:'offline',message:'offline',providers:[]},project_analysis:{status:'configured',message:'offline'},llm:{status:'unconfigured',message:'offline'},fetch:{status:'available',browser_fallback:false,message:'offline'},platforms:[],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40}}});
      if(url.pathname==='/api/projects')return route.fulfill({json:{projects:[]}});
      if(url.pathname==='/api/projects/simple-review/results')return route.fulfill({json:current});
    }
    if(request.method()==='POST'&&url.pathname.startsWith('/api/projects/simple-review/')){
      const action=url.pathname.split('/').at(-1)!,body=request.postDataJSON();writes.push({action,body});
      if(action==='edit'){
        expect(body.expected_version).toBe(current.version!.version);
        current={...current,current_version:current.current_version+1,version:{...current.version!,version:current.current_version+1,analysis:body.analysis,status:'analyzed',confirmation:null},points:[]};
        current.versions.push({version:current.current_version,status:'analyzed',created_at:'2026-10-19T06:00:00Z'});
      }else if(action==='confirm'){
        expect(body.version).toBe(current.version!.version);
        current.version!.confirmation={confirmed_at:'2026-10-19T06:00:01Z',acknowledged_skipped_prerequisites:body.acknowledged_skipped_prerequisites};
      }else if(action==='search'){
        expect(body.version).toBe(current.version!.version);current.version!.status='partial';
        current.points=current.version!.analysis!.knowledge_points.filter(p=>p.selection==='learn').map(p=>({project_knowledge_point_id:p.id,name:p.name,selection:p.selection,status:'partial',batch_id:null,job_id:null,knowledge_point_id:p.id,result:{knowledge_point_id:p.id,text:p.name,items:[],discovery_items:[],total_matches:0}}));
      }else{unexpected.push(url.pathname);return route.abort();}
      return route.fulfill({json:current});
    }
    unexpected.push(`${request.method()} ${url.pathname}`);return route.abort();
  });
  await page.goto('/?project=simple-review&version=1');
  await page.getByRole('heading',{name:'确认知识点 · v1'}).waitFor();
  return {writes,getView:()=>current,assertClean:()=>{expect(unexpected).toEqual([]);expect(runtime).toEqual([]);expect(consoleErrors).toEqual([]);}};
}
const point=(page:Page,id:string)=>page.locator(`.simple-knowledge-point[data-point-id="${id}"]`);
test('professional-name selection and order preserve all historical fields, recover drafts, and confirm without invented prerequisite acknowledgements',async({page},info)=>{
  const original=fixture(),s=await setup(page,original);
  const panel=page.locator('.simple-knowledge-review');
  await expect(panel.getByRole('textbox')).toHaveCount(3);await expect(panel.getByRole('checkbox')).toHaveCount(3);await expect(panel.getByRole('spinbutton')).toHaveCount(3);
  await expect(panel.locator('textarea,details')).toHaveCount(0);
  await expect(panel).not.toContainText(/隐藏历史|原功能|先修|学习目标|本单元|已检查草案/);
  await expect(point(page,'k3').getByRole('checkbox')).not.toBeChecked();
  await point(page,'k1').getByRole('textbox').fill('pygame 键盘事件处理');
  await point(page,'k1').getByRole('spinbutton').fill('4');
  await point(page,'k2').getByRole('spinbutton').fill('1');
  await point(page,'k1').getByRole('checkbox').focus();await page.keyboard.press('Space');
  await page.reload();await expect(point(page,'k1').getByRole('textbox')).toHaveValue('pygame 键盘事件处理');await expect(point(page,'k1').getByRole('checkbox')).not.toBeChecked();
  expect(s.writes).toEqual([]);
  for(const viewport of[{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
    await page.setViewportSize(viewport);await page.screenshot({path:info.outputPath(`simple-review-${viewport.name}.png`),fullPage:false,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
    for(const name of await panel.getByRole('textbox').all())expect(await name.evaluate(n=>n.getBoundingClientRect().width)).toBeGreaterThan(120);
  }
  await panel.getByRole('button',{name:'查找视频',exact:true}).click();
  await page.getByRole('region',{name:'视频封面',exact:true}).waitFor();
  expect(s.writes.map(w=>w.action)).toEqual(['edit','confirm','search']);
  const expected=structuredClone(original.version!.analysis!) as ProjectAnalysis;
  Object.assign(expected.knowledge_points[0],{name:'pygame 键盘事件处理',learning_order:4,selection:'skip'});expected.knowledge_points[1].learning_order=1;
  expect(s.writes[0].body.analysis).toEqual(expected);expect(s.writes[1].body).toEqual({version:2,acknowledged_skipped_prerequisites:[]});expect(s.writes[2].body).toEqual({version:2});
  await expect(page.getByRole('navigation',{name:'已选知识点'}).getByRole('button',{name:'矩形碰撞检测',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation',{name:'已选知识点'}).getByRole('button',{name:'pygame 键盘事件处理',exact:true})).toHaveCount(0);
  expect(await page.locator('.stage-content').innerText()).toBe('');expect(s.getView().version!.analysis).toEqual(expected);s.assertClean();
});
test('confirmed left navigation follows edited priority and preserves original order for equal priorities',async({page})=>{
  const original=fixture();original.version!.analysis!.knowledge_points[2].selection='learn';
  const s=await setup(page,original);
  await point(page,'k1').getByRole('spinbutton').fill('4');
  await point(page,'k2').getByRole('spinbutton').fill('1');
  await point(page,'k3').getByRole('spinbutton').fill('4');
  await page.getByRole('button',{name:'查找视频',exact:true}).click();
  const nav=page.getByRole('navigation',{name:'已选知识点'});
  await expect(nav.getByRole('button')).toHaveText(['全部','矩形碰撞检测','pygame 事件循环','状态机']);
  await nav.getByRole('button',{name:'矩形碰撞检测',exact:true}).focus();await page.keyboard.press('Tab');
  await expect(nav.getByRole('button',{name:'pygame 事件循环',exact:true})).toBeFocused();
  expect(s.writes.map(w=>w.action)).toEqual(['edit','confirm','search']);
  // Display sorting must not reorder or alter the saved source array.
  expect(s.writes[0].body.analysis.knowledge_points.map((p:{id:string})=>p.id)).toEqual(['k1','k2','k3']);
  expect(s.writes[1].body).toEqual({version:2,acknowledged_skipped_prerequisites:[]});s.assertClean();
});
test('saving an edited term creates one version; empty selection creates no search; history remains read-only',async({page})=>{
  const s=await setup(page);
  await point(page,'k1').getByRole('textbox').fill('pygame 主事件循环');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();await page.getByRole('heading',{name:'确认知识点 · v2'}).waitFor();
  expect(s.writes.map(w=>w.action)).toEqual(['edit']);expect(s.getView().version!.confirmation).toBeNull();
  for(const checkbox of await page.locator('.simple-knowledge-review').getByRole('checkbox').all())if(await checkbox.isChecked())await checkbox.uncheck();
  await page.getByRole('button',{name:'保存选择',exact:true}).click();await expect(page.getByRole('status')).toContainText('没有勾选知识点');
  expect(s.writes.map(w=>w.action)).toEqual(['edit','edit','confirm']);expect(s.writes.at(-1)!.body).toEqual({version:3,acknowledged_skipped_prerequisites:[]});
  s.assertClean();
  // A separate restored historical version is view-only; no hidden write is allowed.
  const old=fixture();old.current_version=2;await page.unrouteAll();
  const historic=await setup(page,old);for(const control of await page.locator('.simple-knowledge-review').locator('input').all())await expect(control).toBeDisabled();
  await expect(page.locator('.simple-knowledge-review').getByRole('button')).toHaveCount(0);expect(historic.writes).toEqual([]);historic.assertClean();
});
