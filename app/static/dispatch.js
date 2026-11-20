import {board, explanation, grid, localTime, text, waveOf, waves} from './board.js';

const el = id => document.getElementById(id);
const parts = {orders:'团餐订单',substitutions:'套餐替代',windows:'到站窗口',capacity:'装车容量',allocation:'备用递补',reconcile:'份数对账',archive:'交接签单',amendments:'补录裁决'};
const desk = {result:JSON.parse(el('initial').textContent),wave:'all',order:'团-008',section:'allocation',receipt:null,amendment:null,pending:false};
const stockStatus = {usable:'可用',expired:'过期',quarantined:'隔离'};
const opLabels = {revise_order:'换餐改签',update_trip:'车辆班次',return_stock:'备用退回'};
const checkLabels = {base_reconciled:'原签单对平',amended_reconciled:'新结论对平',same_ruleset:'同一对账口径',all_adopted:'补录全采用'};
const amendTemplate = JSON.stringify([
  {op:'revise_order',row:{order:'团-008',revision:2,supersedes:1,issued:'2026-11-20T09:25:00+08:00',station:'河西书院',wave:'午线',qty:15,meal:'菌菇素',locked:false,status:'active'}},
  {op:'update_trip',row:{truck:'柿-04',wave:'午线',capacity:28,departure:'2026-11-20T11:16:00+08:00',stops:[{station:'创客园',eta:'2026-11-20T11:44:00+08:00'},{station:'运动馆',eta:'2026-11-20T12:05:00+08:00'}]}},
  {op:'return_stock',lot:'备-01',qty:5}
],null,2);

function feedback(message, error=false) {el('notice').textContent=message;el('notice').toggleAttribute('data-error',error);}
function currentOrder() {
  const rows=desk.result.allocation.rows.filter(row=>desk.wave==='all'||waveOf(row)===desk.wave);
  return rows.find(row=>row.order===desk.order) ?? rows[0];
}
function render() {
  const {result,section} = desk;
  const ledger=result.reconcile.totals, spare=ledger.spare;
  const order=currentOrder(); desk.order=order?.order;
  el('batch-name').textContent=result.batch;
  el('metrics').innerHTML=[['应送',ledger.requested,''],['实发',ledger.shipped,'ship'],['缺配',ledger.short,'short'],['争议',ledger.disputed,'dispute'],['备用实发',spare.used,'']].map(([label,value,cls])=>`<div class="tally ${cls}"><span>${label}</span><strong>${value} <small>份</small></strong></div>`).join('');
  el('wave-filter').replaceChildren(new Option('全部波次','all'),...waves(result).map(group=>new Option(group.wave,group.wave)));
  el('wave-filter').value=desk.wave;
  const positions=new Map([...el('wave-board').querySelectorAll('.wave')].map(panel=>[panel.getAttribute('aria-label'),panel.querySelector('.wave-body').scrollTop]));
  el('wave-board').innerHTML=board(result,desk.wave,desk.order);
  el('wave-board').querySelectorAll('.wave').forEach(panel=>{panel.querySelector('.wave-body').scrollTop=positions.get(panel.getAttribute('aria-label'))??0;});
  el('detail-title').textContent=parts[section]; el('active-order').textContent=order && section!=='archive' && section!=='amendments' ? `${order.order} · ${order.station ?? '待核'}` : '';
  el('detail').innerHTML=inspect(order);
  el('stock').innerHTML=`<div class="spare-math"><span>申报 <b>${spare.declared}</b></span><span>实发 <b>${spare.used}</b></span><span>结余 <b>${spare.left}</b></span><span>过期 <b>${spare.expired}</b></span><span>隔离 <b>${spare.quarantined}</b></span></div>`+
    grid(['批号','餐品','已发 / 申报','状态'],result.allocation.stock.filter(row=>row.kind==='spare').map(row=>[row.lot,row.meal??row.raw.meal,`${row.loaded} / ${row.qty}`,stockStatus[row.status]]));
  el('balance').textContent=result.reconcile.status==='MATCHED'?'送餐与备用餐已对平':'份数待复核';
  el('version').textContent=`${localTime(result.at)} · 上海时间 · ${result.ruleset}`;
  document.querySelectorAll('nav a').forEach(link=>{if(link.hash===`#${section}`)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
}
function inspect(order) {
  const {result,section}=desk;
  if(section==='archive')return signature();
  if(section==='amendments')return amendments();
  if(section==='reconcile') {
    const totals=result.reconcile.totals;
    return `<div class="slip"><strong>${totals.requested} = ${totals.shipped} + ${totals.short} + ${totals.disputed}</strong><span>送餐差额 ${totals.difference} 份 · 备用差额 ${totals.spare.difference} 份</span></div>`+
      grid(['波次','应送','实发','缺配','争议'],waves(result).map(row=>[row.wave,row.qty,row.shipped,row.short,row.disputed]));
  }
  if(section==='capacity')return grid(['车辆','波次','装载 / 容量','余位','车次行'],result.allocation.vehicles.filter(row=>desk.wave==='all'||row.wave===desk.wave).map(row=>[row.truck,row.wave,`${row.loaded} / ${row.capacity} 份`,row.remaining,row.line]));
  if(section==='substitutions')return grid(['原餐','批准的备用餐','判定','规则行'],[
    ...result.substitutions.rows.map(row=>[row.requested,row.spare,'可替代',row.line]),
    ...result.substitutions.issues.map(row=>[row.raw?.requested,row.raw?.spare,row.code,row.line])]);
  if(section==='windows')return grid(['波次','站点','开始','截止','窗口行'],result.windows.rows.filter(row=>desk.wave==='all'||row.wave===desk.wave).map(row=>[row.wave,row.station,localTime(row.start),localTime(row.end),row.line]));
  if(section==='orders')return grid(['订单','站点','版本','应送','原始行','状态'],result.orders.rows.filter(row=>desk.wave==='all'||waveOf(row)===desk.wave).map(row=>[row.order,row.station,row.revision,row.qty,row.revision_lines.join('、'),({active:'有效',cancelled:'已撤销',conflict:'争议'})[row.state]]));
  if(!order)return '<p class="empty">选择订单查看发餐明细。</p>';
  return `<div class="slip"><strong>${text(order.meal)}</strong><span>应送 ${order.qty} 份</span><span>实发 ${order.shipped} 份</span><span>优先序 ${text(order.rank)}</span><span class="status-word">${explanation(order.code)}</span></div>`+
    grid(['车辆','到站','批号','实发餐品','份数','批准行'],order.loads.map(load=>[load.truck,localTime(load.arrival),load.lot,load.meal,load.qty,load.substitution_line??'原餐']));
}
function signature() {
  const run=desk.receipt;
  if(!run)return '<p class="empty">计算发餐后生成交接签单。</p><button data-history>查看交接历史</button><div id="history"></div>';
  return `<div class="slip"><strong>${text(run.manifest.batch)}</strong><span>${text(run.manifest.generated_at)}</span></div><p class="digest">${text(run.manifest.digest)}</p>
  <div class="receipt"><button data-rerun>重跑发餐</button><a class="download" href="/api/runs/${text(run.id)}/export">下载交接证据</a><button data-history>查看交接历史</button></div>
  ${run.signature?`<p>已交接 · ${text(run.signature.reviewer)}</p>`:'<form id="sign" class="receipt"><label>签单人 <input name="reviewer" maxlength="100" required></label><button>确认交接</button></form>'}<div id="history"></div>`;
}
function amendments() {
  const run=desk.receipt;
  if(!run)return '<p class="empty">先计算发餐生成交接签单，再登记补录。</p>';
  const lineage=run.lineage??{};
  let head=`<div class="slip"><strong>${text(run.manifest.batch)}</strong><span>当前签单 ${text(run.id.slice(0,12))}</span>`;
  if(lineage.amendment)head+=`<span>由补录 ${text(lineage.amendment)} 生成 · 替换签单 ${text(String(lineage.supersedes).slice(0,12))}</span>`;
  if(lineage.superseded_by?.length)head+=`<span>被补录 ${text(lineage.superseded_by.map(item=>item.amendment).join('、'))} 替换</span>`;
  head+='</div>';
  const form=`<form id="amend" class="amend-form"><label>补录单号 <input name="amendment" maxlength="100" required placeholder="补录-001"></label><textarea name="operations" rows="9" spellcheck="false">${text(amendTemplate)}</textarea><div><button class="accent">裁决补录</button></div></form>`;
  return head+form+(desk.amendment?verdictView(desk.amendment):'');
}
function verdictView(record) {
  const ready=record.handover.ready;
  const checks=Object.entries(record.handover.checks).map(([key,ok])=>`<span class="status-word ${ok?'good':'bad'}">${text(checkLabels[key]??key)}${ok?'✓':'✗'}</span>`).join(' ');
  const ops=grid(['序号','补录','判定','说明'],record.operations.map(op=>[op.index,opLabels[op.op]??op.op??'—',op.verdict==='adopted'?'采用':'退回',op.summary??op.detail??'']));
  const head=`<div class="slip"><strong>补录 ${text(record.amendment)}</strong><span>采用 ${record.adopted} · 退回 ${record.rejected}</span><span class="status-word ${ready?'good':'bad'}">${ready?'可交付接班':'暂不能交接'}</span></div><p class="checks">${checks}</p>`;
  const replaced=record.run?`<p class="digest">新签单 ${text(record.run.slice(0,12))} 替换 ${text(record.base_run.slice(0,12))}</p>`:'<p class="empty">没有补录被采用，未形成新结论。</p>';
  return head+ops+replaced+(record.diff?diffView(record.diff):'');
}
const ch=(before,after,key)=>`${before?before[key]:'—'} → ${after?after[key]:'—'}`;
function diffView(diff) {
  const t=diff.totals;
  const totals=grid(['项目','签单前','补录后'],[
    ['应送',t.before.requested,t.after.requested],['实发',t.before.shipped,t.after.shipped],
    ['缺配',t.before.short,t.after.short],['争议',t.before.disputed,t.after.disputed],
    ['备用申报',t.before.spare.declared,t.after.spare.declared],['备用实发',t.before.spare.used,t.after.spare.used],
    ['备用结余',t.before.spare.left,t.after.spare.left],['对账',t.before.status,t.after.status]]);
  const orders=grid(['订单','餐品','应送','实发','缺配','争议'],diff.orders.map(row=>[row.order,ch(row.before,row.after,'meal'),ch(row.before,row.after,'qty'),ch(row.before,row.after,'shipped'),ch(row.before,row.after,'short'),ch(row.before,row.after,'disputed')]));
  const vehicles=grid(['车辆','装载','余位'],diff.vehicles.map(row=>[row.truck,ch(row.before,row.after,'loaded'),ch(row.before,row.after,'remaining')]));
  const lots=grid(['批号','餐品','已发','结余','状态'],diff.lots.map(row=>[row.lot,ch(row.before,row.after,'meal'),ch(row.before,row.after,'loaded'),ch(row.before,row.after,'left'),`${stockStatus[row.before?.status]??'—'} → ${stockStatus[row.after?.status]??'—'}`]));
  return `<h3 class="diff-head">份数前后</h3>${totals}<h3 class="diff-head">订单变化</h3>${orders}<h3 class="diff-head">车辆变化</h3>${vehicles}<h3 class="diff-head">批号变化</h3>${lots}`;
}
async function api(path, body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(result.message||'发餐请求失败，请重试。');return result;
}
async function run(task) {
  if(desk.pending)return;desk.pending=true;feedback('调度中…');
  try{await task();}catch(error){feedback(error.message,true);}finally{desk.pending=false;}
}
function useReceipt(receipt){desk.receipt=receipt;desk.result=receipt.result;desk.amendment=null;if(!desk.result.reconcile.rows.some(row=>row.wave===desk.wave))desk.wave='all';render();}
function setSection(){const next=location.hash.slice(1);desk.section=parts[next]?next:'allocation';render();}
el('operate').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
  const receipt=desk.receipt?await api(`/api/runs/${desk.receipt.id}/rerun`,{}):await api('/api/runs',{sample:el('sample').value});
  useReceipt(receipt);feedback(receipt.reused?'重跑调度一致':'发餐已归档');
});});
el('sample').addEventListener('change',event=>{location.href=`/?sample=${event.target.value}${location.hash}`;});
el('wave-filter').addEventListener('change',event=>{desk.wave=event.target.value;render();});
el('wave-board').addEventListener('click',event=>{const item=event.target.closest('[data-order]');if(!item)return;desk.order=item.dataset.order;location.hash='allocation';desk.section='allocation';render();el('wave-board').querySelector('[aria-pressed=true]')?.focus({preventScroll:true});});
el('pick-file').addEventListener('click',()=>el('upload').click());
el('upload').addEventListener('change',event=>{const [file]=event.target.files;if(!file)return;run(async()=>{
  let source;try{source=JSON.parse(await file.text());}catch{throw new Error('排班格式错误，请选择 JSON 文件。');}
  useReceipt(await api('/api/runs',{source}));feedback('排班已归档');
}).finally(()=>{event.target.value='';});});
el('detail').addEventListener('click',event=>{const button=event.target.closest('[data-rerun],[data-history],[data-id]');if(!button)return;run(async()=>{
  if(button.hasAttribute('data-rerun')){useReceipt(await api(`/api/runs/${desk.receipt.id}/rerun`,{}));feedback('重跑调度一致');}
  if(button.hasAttribute('data-history')){const {runs}=await api('/api/runs');el('history').replaceChildren(...runs.map(entry=>{const action=document.createElement('button');action.dataset.id=entry.id;action.textContent=`${entry.batch} · ${localTime(entry.generated_at)}`;return action;}));feedback(runs.length?`${runs.length} 笔签单`:'暂无签单');}
  if(button.dataset.id){useReceipt(await api(`/api/runs/${button.dataset.id}`));feedback('已载入交接签单');}
});});
el('detail').addEventListener('submit',event=>{if(event.target.id==='amend'){event.preventDefault();run(async()=>{
  const data=new FormData(event.target);
  let operations;try{operations=JSON.parse(data.get('operations'));}catch{throw new Error('补录操作须为 JSON 数组。');}
  if(!Array.isArray(operations)||!operations.length)throw new Error('补录操作须为 JSON 数组。');
  const record=await api(`/api/runs/${desk.receipt.id}/amendments`,{amendment:data.get('amendment'),operations});
  if(record.run)useReceipt(await api(`/api/runs/${record.run}`));
  desk.amendment=record;desk.section='amendments';render();
  feedback(record.rejected?`补录已裁决：采用 ${record.adopted} 条，退回 ${record.rejected} 条`:'补录已裁决，全部采用');
});return;}
  if(event.target.id!=='sign')return;event.preventDefault();run(async()=>{
  desk.receipt.signature=await api(`/api/runs/${desk.receipt.id}/sign`,{reviewer:new FormData(event.target).get('reviewer'),digest:desk.receipt.manifest.digest});render();feedback('交接签单完成');
});});
addEventListener('hashchange',setSection);setSection();
