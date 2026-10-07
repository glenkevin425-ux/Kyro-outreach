const KEY='kyro.v2';
const seed={
 tasks:[
  {id:1,title:'Review structural analysis',due:'Today',priority:'High',done:false},
  {id:2,title:'Work on Kcreatives homepage',due:'Today',priority:'High',done:false},
  {id:3,title:'Study for 2 hours',due:'Today',priority:'Medium',done:false},
  {id:4,title:'Review Kyro project roadmap',due:'Today',priority:'Medium',done:false},
  {id:5,title:'Send Golf Hotel proposal',due:'Tomorrow',priority:'High',done:false}
 ],
 projects:[
  {id:1,name:'Kcreatives',desc:'Branding, graphic design and client work',progress:82},
  {id:2,name:'Kyro',desc:'Personal command center',progress:48},
  {id:3,name:'Fixly',desc:'Product development',progress:64},
  {id:4,name:'MMUST HostelHub',desc:'Student booking platform',progress:41}
 ],
 income:[{id:1,amount:31450,source:'October income',date:'October 2026'}],
 spending:[{name:'Needs',amount:14467},{name:'Savings',amount:8177},{name:'Business',amount:5032},{name:'Other',amount:3774}],
 ideas:[
  {id:1,title:'Kcreatives client portal',body:'A simple client workspace for projects, deliverables and updates.'},
  {id:2,title:'Student command center',body:'A focused workspace for university students.'}
 ],
 goals:[
  {id:1,title:'Build Kcreatives into a consistent side business',progress:42},
  {id:2,title:'Maintain a strong university performance',progress:58},
  {id:3,title:'Build a 3-month emergency buffer',progress:31},
  {id:4,title:'Ship Kyro V1',progress:72}
 ],
 activity:[
  {text:'Logged October income — KSh 31,450',time:'Today'},
  {text:'Kyro personal command center updated',time:'Today'},
  {text:'Kcreatives moved to 82%',time:'Today'}
 ]
};
let state;
try{state=JSON.parse(localStorage.getItem(KEY)||'null')||seed}catch(e){state=seed}
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const money=n=>'KSh '+Number(n||0).toLocaleString('en-KE');
const incomeTotal=()=>state.income.reduce((s,x)=>s+Number(x.amount||0),0);
const allocationTotal=()=>state.spending.reduce((s,x)=>s+Number(x.amount||0),0);
const goalAverage=()=>state.goals.length?Math.round(state.goals.reduce((s,x)=>s+Number(x.progress||0),0)/state.goals.length):0;
function save(){try{localStorage.setItem(KEY,JSON.stringify(state))}catch(e){}}
function log(text){state.activity.unshift({text,time:'Just now'});state.activity=state.activity.slice(0,20);save()}
function showView(id){
 document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id===id));
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===id));
 $('sidebar').classList.remove('open');$('overlay').classList.remove('open');render();
}
function openModal(html){$('modalBody').innerHTML=html;$('modal').classList.add('open');setTimeout(()=>{const x=$('modalBody').querySelector('input');if(x)x.focus()},0)}
function closeModal(){$('modal').classList.remove('open')}
function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');clearTimeout(window.__kyroToast);window.__kyroToast=setTimeout(()=>t.classList.remove('show'),1800)}
function taskHTML(t){return '<div class="task '+(t.done?'done':'')+'"><button type="button" class="check '+(t.done?'done':'')+'" data-action="toggle-task" data-id="'+t.id+'">'+(t.done?'✓':'')+'</button><div class="task-main"><div class="task-title">'+esc(t.title)+'</div><div class="task-meta">'+esc(t.due)+' · '+esc(t.priority)+'</div></div><span class="pill '+(t.priority==='High'?'amber':'')+'">'+(t.done?'Done':esc(t.priority))+'</span></div>'}
function projectHTML(p){return '<div class="project"><div class="project-row"><span class="project-name">'+esc(p.name)+'</span><span class="pill">'+p.progress+'%</span></div><div class="progress"><div class="bar" style="width:'+p.progress+'%"></div></div></div>'}
function projectCard(p){return '<div class="card"><span class="pill blue">Project</span><h3>'+esc(p.name)+'</h3><p style="color:#667085;line-height:1.5">'+esc(p.desc)+'</p><div class="project-row"><span style="font-size:12px;color:#667085">Progress</span><strong>'+p.progress+'%</strong></div><div class="progress"><div class="bar" style="width:'+p.progress+'%"></div></div><div style="margin-top:14px"><button type="button" class="secondary" data-action="advance-project" data-id="'+p.id+'">Advance</button></div></div>'}
function activityHTML(a){return '<div class="activity-item"><span class="dot"></span><div><div>'+esc(a.text)+'</div><div class="activity-time">'+esc(a.time)+'</div></div></div>'}
function render(){
 $('statTasks').textContent=state.tasks.filter(t=>!t.done&&t.due==='Today').length;
 $('statProjects').textContent=state.projects.length;
 $('statIncome').textContent=money(incomeTotal());
 $('spendingTotal').textContent=money(allocationTotal());
 $('allocationCheck').textContent=money(allocationTotal());
 $('spendingBreakdown').innerHTML=state.spending.map(x=>{const pct=allocationTotal()?Math.round(x.amount/allocationTotal()*100):0;return '<div class="breakRow"><span>'+esc(x.name)+'</span><div class="breakTrack"><div class="breakFill" style="width:'+pct+'%"></div></div><b>'+pct+'%</b></div>'}).join('');
 $('dashTasks').innerHTML=state.tasks.filter(t=>t.due==='Today').slice(0,5).map(taskHTML).join('')||'<div class="empty"><strong>No tasks today</strong>Your day is clear.</div>';
 $('taskList').innerHTML=state.tasks.map(taskHTML).join('')||'<div class="card empty"><strong>No tasks yet</strong>Add your first task.</div>';
 $('dashProjects').innerHTML=state.projects.slice(0,4).map(projectHTML).join('');
 $('projectList').innerHTML=state.projects.map(projectCard).join('');
 $('upcoming').innerHTML=state.tasks.filter(t=>t.due!=='Today'&&!t.done).slice(0,4).map(t=>'<div class="task"><div class="task-main"><div class="task-title">'+esc(t.title)+'</div><div class="task-meta">'+esc(t.due)+'</div></div><span class="pill">'+esc(t.priority)+'</span></div>').join('')||'<div class="empty">Nothing upcoming.</div>';
 $('dashActivity').innerHTML=state.activity.slice(0,5).map(activityHTML).join('');
 $('activityList').innerHTML=state.activity.map(activityHTML).join('');
 const total=incomeTotal();
 $('financeStats').innerHTML='<div class="stat"><div class="stat-top">Income</div><div class="finance-number positive">'+money(total)+'</div><div class="stat-note">logged</div></div><div class="stat"><div class="stat-top">Entries</div><div class="finance-number">'+state.income.length+'</div><div class="stat-note">income records</div></div><div class="stat"><div class="stat-top">Average</div><div class="finance-number">'+money(state.income.length?total/state.income.length:0)+'</div><div class="stat-note">per entry</div></div><div class="stat"><div class="stat-top">Currency</div><div class="finance-number">KES</div><div class="stat-note">Kenyan shilling</div></div>';
 $('incomeList').innerHTML=state.income.map(x=>'<div class="row"><div class="row-main"><div class="row-title">'+money(x.amount)+'</div><div class="row-sub">'+esc(x.source)+' · '+esc(x.date)+'</div></div></div>').join('');
 $('ideaList').innerHTML=state.ideas.map(x=>'<div class="card idea"><span class="pill blue">Idea</span><h3>'+esc(x.title)+'</h3><p>'+esc(x.body)+'</p><button type="button" class="link" data-action="delete-idea" data-id="'+x.id+'">Delete</button></div>').join('');
 $('goalList').innerHTML=state.goals.map(x=>'<div class="row goal"><div class="goal-circle">'+x.progress+'%</div><div class="row-main"><div class="row-title">'+esc(x.title)+'</div><div class="progress"><div class="bar" style="width:'+x.progress+'%"></div></div></div><button type="button" class="secondary" data-action="advance-goal" data-id="'+x.id+'">+10%</button></div>').join('');
}
function openTask(){openModal('<h3>Add task</h3><form id="taskForm"><div class="field"><label>Task</label><input id="fTitle" required placeholder="What needs to be done?"></div><div class="field"><label>Due</label><select id="fDue"><option>Today</option><option>Tomorrow</option><option>This week</option></select></div><div class="field"><label>Priority</label><select id="fPriority"><option>Medium</option><option>High</option><option>Low</option></select></div><div class="modal-actions"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">Add task</button></div></form>')}
function openProject(){openModal('<h3>Add project</h3><form id="projectForm"><div class="field"><label>Name</label><input id="pName" required placeholder="Project name"></div><div class="field"><label>Description</label><input id="pDesc" placeholder="What is this project?"></div><div class="modal-actions"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">Add project</button></div></form>')}
function openFinance(){openModal('<h3>Log income</h3><form id="incomeForm"><div class="field"><label>Amount (KSh)</label><input id="iAmount" type="number" min="1" required placeholder="0"></div><div class="field"><label>Source</label><input id="iSource" required placeholder="Salary, client, side hustle..."></div><div class="modal-actions"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">Log income</button></div></form>')}
function openIdea(){openModal('<h3>Capture idea</h3><form id="ideaForm"><div class="field"><label>Title</label><input id="ideaTitle" required placeholder="Give the idea a name"></div><div class="field"><label>Thought</label><textarea id="ideaBody" rows="5" placeholder="Write it down..."></textarea></div><div class="modal-actions"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">Save idea</button></div></form>')}
function openGoal(){openModal('<h3>Add goal</h3><form id="goalForm"><div class="field"><label>Goal</label><input id="goalTitle" required placeholder="What are you working toward?"></div><div class="modal-actions"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">Add goal</button></div></form>')}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-view]');if(b){e.preventDefault();showView(b.dataset.view);return}
 const a=e.target.closest('[data-action]');if(!a)return;
 e.preventDefault();const id=Number(a.dataset.id);
 if(a.dataset.action==='open-task')openTask();
 else if(a.dataset.action==='close-modal')closeModal();
 else if(a.dataset.action==='toggle-task'){const t=state.tasks.find(x=>x.id===id);if(t){t.done=!t.done;log((t.done?'Completed: ':'Reopened: ')+t.title);render()}}
 else if(a.dataset.action==='advance-project'){const p=state.projects.find(x=>x.id===id);if(p){p.progress=Math.min(100,p.progress+10);log('Advanced '+p.name+' to '+p.progress+'%');render()}}
 else if(a.dataset.action==='advance-goal'){const g=state.goals.find(x=>x.id===id);if(g){g.progress=Math.min(100,g.progress+10);log('Advanced goal: '+g.title);render()}}
 else if(a.dataset.action==='delete-idea'){state.ideas=state.ideas.filter(x=>x.id!==id);log('Deleted an idea');render()}
});
document.addEventListener('submit',e=>{
 if(e.target.id==='taskForm'){e.preventDefault();const title=$('fTitle').value.trim();if(!title)return;state.tasks.unshift({id:Date.now(),title,due:$('fDue').value,priority:$('fPriority').value,done:false});log('Added task: '+title);closeModal();toast('Task added');render()}
 if(e.target.id==='projectForm'){e.preventDefault();const name=$('pName').value.trim();if(!name)return;state.projects.unshift({id:Date.now(),name,desc:$('pDesc').value.trim(),progress:0});log('Created project: '+name);closeModal();toast('Project created');render()}
 if(e.target.id==='incomeForm'){e.preventDefault();const amount=Number($('iAmount').value);const source=$('iSource').value.trim();if(!Number.isFinite(amount)||amount<=0||!source)return;state.income.unshift({id:Date.now(),amount,source,date:new Date().toLocaleDateString('en-KE',{month:'long',year:'numeric'})});log('Logged '+money(amount)+' from '+source);closeModal();toast('Income logged');render()}
 if(e.target.id==='ideaForm'){e.preventDefault();const title=$('ideaTitle').value.trim();if(!title)return;state.ideas.unshift({id:Date.now(),title,body:$('ideaBody').value.trim()});log('Captured idea: '+title);closeModal();toast('Idea saved');render()}
 if(e.target.id==='goalForm'){e.preventDefault();const title=$('goalTitle').value.trim();if(!title)return;state.goals.unshift({id:Date.now(),title,progress:0});log('Created goal: '+title);closeModal();toast('Goal added');render()}
});
$('menu').addEventListener('click',()=>{$('sidebar').classList.add('open');$('overlay').classList.add('open')});
$('overlay').addEventListener('click',()=>{$('sidebar').classList.remove('open');$('overlay').classList.remove('open')});
$('modal').addEventListener('click',e=>{if(e.target===$('modal'))closeModal()});
$('greeting').textContent=(new Date().getHours()<12?'Good morning':new Date().getHours()<17?'Good afternoon':'Good evening')+', Glen.';
$('date').textContent=new Date().toLocaleDateString('en-KE',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
render();
