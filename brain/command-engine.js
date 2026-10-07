/**
 * Kyro Command Engine — code-first natural-language command understanding.
 * Pipeline: normalize -> score intent -> extract entities -> validate -> action.
 * No LLM/API dependency.
 */
(function(root,factory){
  if(typeof module==='object'&&module.exports) module.exports=factory();
  else root.KyroCommandEngine=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const INTENTS=[
    {id:'create_task',patterns:[[/\b(add|create|make|new)\b.*\b(task|todo|to-do)\b/i,5],[/\b(remind|remember)\b.*\b(me)\b.*\b(to|that)\b/i,4],[/\b(i need to|i have to|i should)\b/i,3],[/\bremind me\b/i,4]]},
    {id:'complete_task',patterns:[[/\b(mark|set)\b.*\b(done|complete|completed)\b/i,6],[/\b(complete|finish|done with)\b/i,5],[/\b(check off|tick off)\b/i,5]]},
    {id:'delete_task',patterns:[[/\b(delete|remove|discard)\b.*\b(task|todo|to-do)\b/i,6],[/\b(cancel)\b.*\b(task|todo)\b/i,5]]},
    {id:'edit_task',patterns:[[/\b(edit|change|update|rename)\b.*\b(task|todo|to-do)\b/i,6],[/\bchange\b.*\bdeadline\b/i,5]]},
    {id:'list_tasks',patterns:[[/\b(show|list|see|view)\b.*\b(tasks|todos|to-dos|work)\b/i,6],[/\bwhat('?s| is)\b.*\b(left|remaining)\b/i,4],[/\bmy tasks\b/i,5],[/\bwhat do i have to do\b/i,5]]},
    {id:'search',patterns:[[/\b(search|find|look up|look for)\b/i,6],[/\bwhere can i find\b/i,5],[/\bfind me\b/i,5]]},
    {id:'save_memory',patterns:[[/\b(remember|save|store|keep in mind|note)\b/i,6],[/\bdon'?t forget\b/i,5],[/\bremember this\b/i,6]]},
    {id:'show_memory',patterns:[[/\b(show|list|recall|tell me)\b.*\b(memory|memories|things you remember)\b/i,6],[/\bwhat do you remember\b/i,7]]},
    {id:'forget_memory',patterns:[[/\b(forget|delete|remove)\b.*\b(memory|memories)\b/i,7],[/\bdon'?t remember\b/i,6]]},
    {id:'plan_day',patterns:[[/\b(plan|organize|schedule)\b.*\b(today|my day)\b/i,7],[/\bplan my day\b/i,8],[/\bwhat should i do today\b/i,6]]},
    {id:'plan_tomorrow',patterns:[[/\b(plan|organize|schedule)\b.*\b(tomorrow)\b/i,8],[/\bplan for tomorrow\b/i,8]]},
    {id:'add_idea',patterns:[[/\b(add|save|capture|record)\b.*\b(idea|ideas)\b/i,7],[/\bidea\b.*\b(save|capture|add)\b/i,6]]},
    {id:'start_focus',patterns:[[/\b(start|begin)\b.*\b(focus|deep work|focus session)\b/i,7],[/\bfocus for\b/i,6],[/\bwork on\b.*\bfor\s+\d+\s*(minutes?|mins?|hours?|hrs?)\b/i,5]]},
    {id:'stop_focus',patterns:[[/\b(stop|end|finish|cancel)\b.*\b(focus|focus session)\b/i,7]]},
    {id:'inspect_project',patterns:[[/\b(review|inspect|check|look at)\b.*\b(project|projects)\b/i,6],[/\bwhat('?s| is)\b.*\b(project)\b/i,4],[/\b(project|projects)\b.*\bstatus\b/i,6]]},
    {id:'github_status',patterns:[[/\b(github|git hub)\b.*\b(status|state|activity|commits|repo|repository|branch)\b/i,7],[/\b(check|inspect|show|review)\b.*\b(github|repo|repository)\b/i,6],[/\bwhat('?s| is)\b.*\b(github|repo)\b/i,5]]},
    {id:'github_commit',patterns:[[/\b(commit|save)\b.*\b(changes|code)\b.*\b(github|repo|repository)?\b/i,6],[/\bcommit\b.*\bto\b.*\b(main|branch|github)\b/i,7]]},
    {id:'open_project',patterns:[[/\b(open|launch|start)\b.*\b(project|app|site|website|repo)\b/i,6],[/\bopen\b.*\bkyro\b/i,5]]},
    {id:'help',patterns:[[/^help$/i,8],[/\bwhat can you do\b/i,9],[/\bhow do i use you\b/i,8]]}
  ];

  function normalize(input){
    return String(input==null?'':input).normalize('NFKC')
      .replace(/[“”]/g,'"').replace(/[‘’]/g,"'")
      .replace(/\s+/g,' ').trim();
  }
  function clean(value){return normalize(value).replace(/^[\s,.:;-]+|[\s,.:;-]+$/g,'').trim();}
  function extractDate(text){
    const s=text.toLowerCase();
    const terms=[['day_after_tomorrow','day after tomorrow'],['today','today'],['tomorrow','tomorrow'],['next_week','next week'],
      ['next_monday','next monday'],['next_tuesday','next tuesday'],['next_wednesday','next wednesday'],
      ['next_thursday','next thursday'],['next_friday','next friday'],['next_saturday','next saturday'],['next_sunday','next sunday']];
    for(const [value,matched] of terms)if(s.includes(matched))return {value,matched};
    const relative=s.match(/\bin\s+(\d+)\s+(day|days|week|weeks)\b/);
    if(relative)return {value:'in_'+relative[1]+'_'+relative[2],matched:relative[0]};
    const iso=s.match(/\b(20\d{2}-\d{2}-\d{2})\b/);
    return iso?{value:iso[1],matched:iso[1]}:null;
  }
  function extractTime(text){
    const s=text.toLowerCase();
    const m=s.match(/\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\b/);
    if(!m)return null;
    let hour=Number(m[1]),minute=m[2]||'00',meridiem=m[3]||null;
    if(meridiem==='pm'&&hour<12)hour+=12;
    if(meridiem==='am'&&hour===12)hour=0;
    if(!meridiem&&hour>23)return null;
    return String(hour).padStart(2,'0')+':'+minute;
  }
  function extractDuration(text){
    const m=text.toLowerCase().match(/\b(?:for\s*)?(\d+)\s*(minutes?|mins?|hours?|hrs?)\b/);
    if(!m)return null;
    const n=Number(m[1]),unit=m[2];
    return unit.startsWith('hour')||unit.startsWith('hr')?n*60:n;
  }
  function extractPriority(text){
    const s=text.toLowerCase();
    if(/\b(urgent|critical|highest|p0|priority\s*1)\b/.test(s))return 'urgent';
    if(/\b(high|important|priority\s*2|p1)\b/.test(s))return 'high';
    if(/\b(low|minor|priority\s*4|p3)\b/.test(s))return 'low';
    return null;
  }
  function extractProject(text){
    const quoted=text.match(/["']([^"']+)["']/);
    if(quoted)return clean(quoted[1]);
    const known=['kyro','kcreatives','mmust hostelhub','kyro outreach','fixly'];
    const lower=text.toLowerCase(),hit=known.find(x=>lower.includes(x));
    return hit?hit.replace(/\b\w/g,c=>c.toUpperCase()):null;
  }
  function extractTarget(text){
    const quoted=text.match(/["']([^"']+)["']/);
    if(quoted)return clean(quoted[1]);
    return clean(text.replace(/\b(today|tomorrow|next week|urgent|high priority|low priority)\b/gi,''));
  }
  function stripLead(text,intent){
    let value=text;
    const patterns={
      create_task:[/^(please\s+)?(add|create|make|new)\s+(a\s+)?(task|todo|to-do)\s*/i,/^(please\s+)?(remind|remember)\s+me\s+(to\s+)?/i,/^(please\s+)?(i need to|i have to|i should)\s+/i],
      save_memory:[/^(please\s+)?(remember|save|store|note)\s+(that|this)?\s*/i,/^(please\s+)?keep\s+in\s+mind\s+/i],
      add_idea:[/^(please\s+)?(add|save|capture|record)\s+(this\s+)?(idea)?\s*/i],
      search:[/^(please\s+)?(search|find|look up|look for)\s*/i]
    };
    for(const re of patterns[intent]||[])value=value.replace(re,'');
    return clean(value);
  }
  function extractTask(text,intent){
    let value=stripLead(text,intent);
    const date=extractDate(value);
    if(date)value=value.replace(date.matched,'');
    value=value.replace(/\b(at|by|on|for)\s*$/i,'');
    return clean(value);
  }
  function score(text,def){return def.patterns.reduce((n,[p,w])=>n+(p.test(text)?w:0),0);}
  function rank(text){return INTENTS.map(d=>({id:d.id,score:score(text,d)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);}
  function confidence(top,second){
    if(!top)return 0;
    if(!second)return Math.min(.99,.55+top.score*.05);
    return Math.max(0,Math.min(.99,.50+(top.score-second.score)*.07));
  }
  function validate(intent,slots){
    const errors=[];
    if(['create_task','complete_task','delete_task','edit_task'].includes(intent)&&!slots.task)errors.push('task');
    if(intent==='save_memory'&&!slots.content)errors.push('content');
    if(intent==='search'&&!slots.query)errors.push('query');
    if(intent==='add_idea'&&!slots.idea)errors.push('idea');
    if(['start_focus'].includes(intent)&&!slots.duration)errors.push('duration');
    return errors;
  }
  function action(intent,s,o){
    switch(intent){
      case 'create_task':return {type:'task.create',payload:{title:s.task,due:s.date,time:s.time,priority:s.priority}};
      case 'complete_task':return {type:'task.complete',payload:{title:s.task}};
      case 'delete_task':return {type:'task.delete',payload:{title:s.task}};
      case 'edit_task':return {type:'task.update',payload:{title:s.task,date:s.date,time:s.time,priority:s.priority}};
      case 'list_tasks':return {type:'task.list',payload:{date:s.date,priority:s.priority}};
      case 'search':return {type:'search',payload:{query:s.query}};
      case 'save_memory':return {type:'memory.save',payload:{content:s.content}};
      case 'show_memory':return {type:'memory.list',payload:{}};
      case 'forget_memory':return {type:'memory.delete',payload:{query:s.query}};
      case 'plan_day':case 'plan_tomorrow':return {type:'plan.create',payload:{scope:s.date||'today'}};
      case 'add_idea':return {type:'idea.create',payload:{content:s.idea}};
      case 'start_focus':return {type:'focus.start',payload:{duration:s.duration,task:s.task}};
      case 'stop_focus':return {type:'focus.stop',payload:{}};
      case 'inspect_project':return {type:'project.inspect',payload:{project:s.project}};
      case 'github_status':return {type:'github.inspect',payload:{project:s.project}};
      case 'github_commit':return {type:'github.commit',payload:{project:s.project}};
      case 'open_project':return {type:'project.open',payload:{project:s.project}};
      case 'help':return {type:'system.help',payload:{}};
      default:return {type:'system.unknown',payload:{original:o}};
    }
  }
  function understand(input){
    const text=normalize(input);
    if(!text)return {ok:false,intent:'unknown',confidence:0,slots:{},action:null,needsClarification:true,clarification:'What would you like Kyro to do?'};
    const ranked=rank(text),top=ranked[0],second=ranked[1],confidenceValue=confidence(top,second);
    if(!top||confidenceValue<.56)return {ok:false,intent:'unknown',confidence:confidenceValue,slots:{},action:null,needsClarification:true,clarification:'I understand the request only partially. Tell me the outcome you want.'};
    const s={};
    if(['create_task','complete_task','delete_task','edit_task'].includes(top.id))s.task=extractTask(text,top.id);
    if(['create_task','edit_task','list_tasks'].includes(top.id)){s.date=extractDate(text)?.value||null;s.time=extractTime(text);s.priority=extractPriority(text);}
    if(top.id==='save_memory')s.content=stripLead(text,'save_memory');
    if(top.id==='show_memory')s.query=null;
    if(top.id==='forget_memory')s.query=stripLead(text,'forget_memory');
    if(top.id==='search')s.query=stripLead(text,'search');
    if(top.id==='add_idea')s.idea=stripLead(text,'add_idea');
    if(top.id==='start_focus'){s.duration=extractDuration(text);s.task=clean(text.replace(/\b(start|begin)\b.*?\b(focus|deep work|focus session)\b/i,'').replace(/\bfor\s+\d+\s*(minutes?|mins?|hours?|hrs?)\b/i,''));}
    if(['inspect_project','github_status','github_commit','open_project'].includes(top.id))s.project=extractProject(text);
    if(top.id==='plan_tomorrow')s.date='tomorrow';
    if(top.id==='plan_day')s.date=/\btomorrow\b/i.test(text)?'tomorrow':'today';
    const errors=validate(top.id,s);
    if(errors.length){
      const question=errors.includes('duration')?'How long should the focus session be?':
        errors.includes('task')?'Which task do you mean?':
        errors.includes('query')?'What should I search for?':
        errors.includes('idea')?'What idea should I save?':'What exactly should I remember?';
      return {ok:false,intent:top.id,confidence:confidenceValue,slots:s,action:null,needsClarification:true,clarification:question};
    }
    return {ok:true,intent:top.id,confidence:confidenceValue,slots:s,action:action(top.id,s,text),needsClarification:false,clarification:''};
  }
  return {version:'0.2.0',normalize,extractDate,extractTime,extractDuration,extractPriority,understand,intents:INTENTS.map(x=>x.id)};
});
