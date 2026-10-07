'use strict';
function clone(v){return JSON.parse(JSON.stringify(v));}
function normalizeState(input){
  const s=input&&typeof input==='object'?input:{};
  return {
    tasks:Array.isArray(s.tasks)?s.tasks.map(t=>({...t})):[],
    memories:Array.isArray(s.memories)?[...s.memories]:[],
    ideas:Array.isArray(s.ideas)?[...s.ideas]:[],
    focus:s.focus||null,
    plans:Array.isArray(s.plans)?s.plans.map(p=>({...p})):[],
    projects:s.projects&&typeof s.projects==='object'?{...s.projects}:{}
  };
}
function findTask(tasks,title){
  const q=String(title||'').toLowerCase().replace(/^the task called\s+/,'').trim();
  return tasks.findIndex(t=>String(t.title||t[0]||'').toLowerCase().includes(q));
}
function ok(state,message,result){return {ok:true,state,result,message};}
function fail(state,message){return {ok:false,state,result:null,message};}
function execute(action,state,now=Date.now()){
  const s=normalizeState(state), p=action?.payload||{};
  switch(action?.type){
    case 'task.create':{
      const task={title:String(p.title||'').trim(),due:p.due||'today',time:p.time||null,priority:p.priority||'normal',status:'open',createdAt:now};
      if(!task.title)return fail(s,'I need a task name before I can create it.');
      s.tasks.unshift(task);return ok(s,'Task created.',task);
    }
    case 'task.complete':{
      const i=findTask(s.tasks,p.title);if(i<0)return fail(s,'I could not find that task.');
      s.tasks[i].status='done';s.tasks[i].completedAt=now;return ok(s,'Task completed.',s.tasks[i]);
    }
    case 'task.delete':{
      const i=findTask(s.tasks,p.title);if(i<0)return fail(s,'I could not find that task.');
      const [removed]=s.tasks.splice(i,1);return ok(s,'Task deleted.',removed);
    }
    case 'task.update':{
      const i=findTask(s.tasks,p.title);if(i<0)return fail(s,'I could not find that task.');
      if(p.date)s.tasks[i].due=p.date;if(p.time)s.tasks[i].time=p.time;if(p.priority)s.tasks[i].priority=p.priority;
      return ok(s,'Task updated.',s.tasks[i]);
    }
    case 'task.list':return ok(s,'Here are your tasks.',s.tasks.filter(t=>t.status!=='done'));
    case 'memory.save':{
      const content=String(p.content||'').trim();if(!content)return fail(s,'I need something to remember.');
      s.memories.unshift({content,createdAt:now});return ok(s,'Memory saved.',s.memories[0]);
    }
    case 'memory.list':return ok(s,s.memories.length?`I have ${s.memories.length} saved memories.`:'I do not have any saved memories yet.',s.memories);
    case 'memory.delete':{
      const q=String(p.query||'').toLowerCase().trim();if(!q)return fail(s,'Tell me which memory to forget.');
      const i=s.memories.findIndex(m=>m.content.toLowerCase().includes(q));if(i<0)return fail(s,'I could not find that memory.');
      const [removed]=s.memories.splice(i,1);return ok(s,'Memory forgotten.',removed);
    }
    case 'idea.create':{
      const content=String(p.content||'').trim();if(!content)return fail(s,'I need an idea to save.');
      s.ideas.unshift(content);return ok(s,'Idea saved.',content);
    }
    case 'focus.start':{
      if(!p.duration)return fail(s,'A focus duration is required.');
      s.focus={duration:p.duration,task:p.task||null,startedAt:now,endsAt:now+Number(p.duration)*60000};
      return ok(s,`Focus session started for ${p.duration} minutes.`,s.focus);
    }
    case 'focus.stop':{
      if(!s.focus)return fail(s,'There is no active focus session.');
      const old=s.focus;s.focus=null;return ok(s,'Focus session stopped.',old);
    }
    case 'plan.create':{
      const plan={scope:p.scope||'today',status:'ready',createdAt:now};s.plans.unshift(plan);
      return ok(s,`Plan created for ${plan.scope}.`,plan);
    }
    case 'system.help':
      return ok(s,'Kyro can create, edit, complete and delete tasks; manage memory and ideas; run focus sessions; plan days; inspect projects; and check GitHub.',null);
    default:return fail(s,'That action is not executable yet.');
  }
}
if(typeof module==='object'&&module.exports)module.exports={execute,normalizeState};
else globalThis.KyroExecutor={execute,normalizeState};