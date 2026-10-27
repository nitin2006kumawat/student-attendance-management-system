const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,o={}){
  const token=$('meta[name="csrf-token"]')?.content||'';
  const r=await fetch(url,{method:o.method||'GET',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:o.body?JSON.stringify(o.body):undefined});
  const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Request failed ('+r.status+')');return d}
function toast(m,bad){const t=document.createElement('div');t.className='toast'+(bad?' bad':'');t.textContent=m;$('#toasts').append(t);setTimeout(()=>t.remove(),3800)}
const openModal=id=>$('#'+id).classList.add('open'),closeModal=id=>$('#'+id).classList.remove('open');
document.addEventListener('click',e=>{const c=e.target.closest('[data-close]');if(c)closeModal(c.dataset.close)});
function confirmDialog(msg){return new Promise(res=>{$('#cmsg').textContent=msg;openModal('confirm');
  const done=v=>{closeModal('confirm');res(v)};$('#cyes').onclick=()=>done(true);$('#cno').onclick=()=>done(false)})}
const debounce=(f,t=250)=>{let h;return(...a)=>{clearTimeout(h);h=setTimeout(()=>f(...a),t)}};
function filters(sel){const o={};$$('[name]',$(sel)).forEach(i=>{if(i.value)o[i.name]=i.value});return new URLSearchParams(o).toString()}
const loadingRows=(tb,n)=>tb.innerHTML=Array(4).fill(`<tr>${'<td><div class="sk"></div></td>'.repeat(n)}</tr>`).join('');
const emptyRow=(n,m)=>`<tr><td colspan="${n}" class="empty">${m}</td></tr>`;
const pct=p=>`<span class="badge ${p>=75?'ok':p>=60?'mid':'low'}">${p}%</span>`;
const badge=s=>`<span class="badge ${s}">${s}</span>`;
async function fillSelects(){
  let meta;for(const s of $$('select[data-src]')){
    const v=s.value;let items;
    if(s.dataset.key){meta=meta||await api('/api/meta');items=meta[s.dataset.key].map(x=>[x,x])}
    else items=(await api(s.dataset.src)).map(x=>[x.id,x[s.dataset.label]+(s.dataset.extra?' ('+x[s.dataset.extra]+')':'')]);
    s.innerHTML=`<option value="">${s.dataset.ph||'All'}</option>`+items.map(([a,b])=>`<option value="${esc(a)}">${esc(b)}</option>`).join('');s.value=v}}
async function loadRule(){const el=$('#rule');if(!el)return;try{const s=await api('/api/settings');
  const formulas={
    exclude:'Present ÷ (Present + Absent)',
    present:'(Present + Leave) ÷ (Present + Absent + Leave)',
    absent:'Present ÷ (Present + Absent + Leave)'
  };
  const t={exclude:'Leave is excluded from the calculation.',present:'Leave counts as Present.',absent:'Leave counts as Absent.'}[s.leave_mode];
  el.innerHTML=`<b>Calculation rule:</b> Attendance % = ${formulas[s.leave_mode]} × 100. ${t} Threshold: <b>${s.threshold}%</b>.`}catch(e){toast(e.message,1)}}
const charts={};
function chart(id,cfg){const el=$('#'+id);if(!el)return;charts[id]?.destroy();Chart.defaults.color='#8d98b8';Chart.defaults.borderColor='#22304f';charts[id]=new Chart(el,cfg)}
function drawCharts(d){
  if(typeof Chart==='undefined'){
    ['cStudents','cSubjects','cTrend'].forEach(id=>{const el=$('#'+id);if(el&&!el.parentElement.querySelector('.chart-offline')){
      const note=document.createElement('p');note.className='empty chart-offline';note.textContent='Charts need an internet connection to load Chart.js.';el.parentElement.append(note)}});
    return
  }
  $$('.chart-offline').forEach(el=>el.remove());
  const sc=d.students.map(s=>s.percentage<d.threshold?'#f43f5e':'#6366f1');
  chart('cStudents',{type:'bar',data:{labels:d.students.map(s=>s.name),datasets:[{label:'Attendance %',data:d.students.map(s=>s.percentage),backgroundColor:sc,borderRadius:6},
    {type:'line',label:'Threshold',data:d.students.map(()=>d.threshold),borderColor:'#f59e0b',borderDash:[6,4],pointRadius:0}]},options:{maintainAspectRatio:false,scales:{y:{min:0,max:100}}}});
  chart('cSubjects',{type:'bar',data:{labels:d.subjects.map(s=>s.subject),datasets:[{label:'Attendance %',data:d.subjects.map(s=>s.percentage),backgroundColor:'#3b82f6',borderRadius:6}]},options:{maintainAspectRatio:false,indexAxis:'y',scales:{x:{min:0,max:100}}}});
  chart('cTrend',{type:'line',data:{labels:d.trend.map(t=>t.date),datasets:[{label:'Daily attendance %',data:d.trend.map(t=>t.percentage),borderColor:'#8b5cf6',backgroundColor:'#8b5cf622',fill:true,tension:.35}]},options:{maintainAspectRatio:false,scales:{y:{min:0,max:100}}}})}
function fillStats(d){const m={sStudents:d.total_students,sRecords:d.records,sOverall:d.overall+'%',sBelow:d.below.length};for(const k in m)if($('#'+k))$('#'+k).textContent=m[k]}
async function topbar(){
  $('#today').textContent=new Date().toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
  $('#menu').onclick=()=>$('#side').classList.toggle('open');
  $('#bell').onclick=e=>{e.stopPropagation();$('#drop').classList.toggle('open')};document.addEventListener('click',()=>$('#drop').classList.remove('open'));
  try{const d=await api('/api/analytics');$('#dot').hidden=!d.below.length;$('#dot').textContent=d.below.length;
    $('#alerts').innerHTML=d.below.slice(0,6).map(s=>`<div>${esc(s.name)}<span class="badge low">${s.percentage}%</span></div>`).join('')||'<p>No alerts 🎉</p>'}catch(e){toast(e.message,1)}}
document.addEventListener('DOMContentLoaded',()=>{topbar();loadRule()});
