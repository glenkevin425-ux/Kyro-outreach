/**
 * Kyro Command Engine — code-first natural-language understanding.
 * Pipeline: normalize -> score intent -> extract slots -> validate -> action.
 */
(function(root,factory){
  if(typeof module==='object'&&module.exports) module.exports=factory();
  else root.KyroCommandEngine=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const INTENTS=[
    {id:'create_task',patterns:[[/\b(add|create|make|new)\b.*\b(task|todo|to-do)\b/i,5],[/\b(remind|remember)\b.*\b(me)\b.*\b(to|that)\b/i,3],[/\b(i need to|i have to|i should)\b/i,2]]},
    {id:'complete_task',patterns:[[/\b(mark|set)\b.*\b(done|complete|completed)\b/i,5],[/\b(complete|finish|done with)\b/i,4],[/\b(check off|tick off)\b/i,4]]},
    {id:'list_tasks',patterns:[[/\b(show|list|see|view)\b.*\b(tasks|todos|to-dos|work)\b/i,5],[/\bwhat('?s| is)\b.*\b(left|remaining)\b/i,3],[/\bmy tasks\b/i,4]]},
    {id:'save_memory',patterns:[[/\b(remember|save|store|keep in mind|note)\b/i,5],[/\bdon'?t forget\b/i,4]]},
    {id:'show_memory',patterns:[[/\b(show|list|recall|tell me)\b.*\b(memory|memories|things you remember)\b/i,5],[/\bwhat do you remember\b/i,6]]},
    {id:'plan_day',patterns:[[/\b(plan|organize|schedule)\b.*\b(today|my day)\b/i,6],[/\bplan my day\b/i,7],[/\bwhat should i do today\b/i,5]]},
    {id:'plan_tomorrow',patterns:[[/\b(plan|organize|schedule)\b.*\b(tomorrow)\b/i,7],[/\bplan for tomorrow\b/i,7]]},
    {id:'inspect_project',patterns:[[/\b(review|inspect|check|look at)\b.*\b(project|projects)\b/i,5],[/\bwhat('?s| is)\b.*\b(project)\b/i,3],[/\b(project|projects)\b.*\bstatus\b/i,5]]},
    {id:'github_status',patterns:[[/\b(github|git hub)\b.*\b(status|state|activity|commits|repo|repository)\b/i,6],[/\b(check|inspect|show|review)\b.*\b(github|repo|repository)\b/i,5],[/\bwhat('?s| is)\b.*\b(github|repo)\b/i,4]]},
    {id:'help',patterns:[[/^help$/i,8],[/\bwhat can you do\b/i,8],[/\bhow do i use you\b/i,7]]}
  ];

  function normalize(input){
    return String(input==null?'':input).normalize('NFKC').replace(/[“”]/g,'"').replace(/[‘’]/g,"'").replace(/\s+/g,' ').trim();
  }
  function cleanPhrase(value){return normalize(value).replace(/^[\s,.:;-]+|[\s,.:;-]+$/g,'').trim();}
  function stripCommandLead(text,intent){
    let value=text;
    const patterns={
      create_task:[/^(please\s+)?(add|create|make|new)\s+(a\s+)?(task|todo|to-do)\s*/i,/^(please\s+)?(remind|remember)\s+me\s+(to\s+)?/i,/^(please\s+)?(i need to|i have to|i should)\s+/i],
      save_memory:[/^(please\s+)?(remember|save|store|note)\s+(that|this)?\s*/i,/^(please\s+)?keep\s+in\s+mind\s+/i,/^(please\s+)?don'?t\s+forget\s+/i],
      complete_task:[/^(please\s+)?(mark|set)\s+/i,/^(please\s+)?(complete|finish)\s+/i,/^(please\s+)?(check|tick)\s+(off\s+)?/i]
    };
    for(const re of patterns[intent]||[]) value=value.replace(re,'');
    return cleanPhrase(value);
  }
  function extractDate(text){
    const s=text.toLowerCase();
    const terms=[['day_after_tomorrow','day after tomorrow'],['today','today'],['tomorrow','tomorrow'],['next_week','next week'],['next_monday','next monday'],['next_tuesday','next tuesday'],['next_wednesday','next wednesday'],['next_thursday','next thursday'],['next_friday','next friday'],['next_saturday','next saturday'],['next_sunday','next sunday']];
    for(const [value,matched] of terms) if(s.includes(matched)) return {value,matched};
    const iso=s.match(/\b(20\d{2}-\d{2}-\d{2})\b/);
    return iso?{value:iso[1],matched:iso[1]}:null;
  }
  function removeDate(text,date){
    if(!date)return cleanPhrase(text);
    const escaped=date.matched.replace(/[-\/\\^$*+?.()|[\]{}]/g,'\\$&');
    return cleanPhrase(text.replace(new RegExp('\\b'+escaped+'\\b','i'),''));
  }
  function extractProject(text){
    const quoted=text.match(/["']([^"']+)["']/);
    if(quoted)return cleanPhrase(quoted[1]);
    const known=['kyro','kcreatives','mmust hostelhub','kyro outreach','fixly'];
    const lower=text.toLowerCase(),hit=known.find(x=>lower.includes(x));
    return hit?hit.replace(/\b\w/g,c=>c.toUpperCase()):null;
  }
  function extractTask(text,intent){
    let value=stripCommandLead(text,intent),date=extractDate(value);
    value=removeDate(value,date).replace(/\b(for|on)\s*$/i,'').trim();
    return cleanPhrase(value);
  }
  function extractMemory(text){return stripCommandLead(text,'save_memory');}
  function scoreIntent(text,def){return def.patterns.reduce((score,[pattern,points])=>score+(pattern.test(text)?points:0),0);}
  function rankIntents(text){return INTENTS.map(def=>({id:def.id,score:scoreIntent(text,def)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);}
  function confidenceFrom(top,second){
    if(!top)return 0;
    if(!second)return Math.min(.99,.55+top.score*.055);
    return Math.max(0,Math.min(.99,.50+(top.score-second.score)*.07));
  }
  function validate(intent,slots){
    const errors=[];
    if((intent==='create_task'||intent==='complete_task')&&!slots.task)errors.push('task');
    if(intent==='save_memory'&&!slots.content)errors.push('content');
    return errors;
  }
  function buildAction(intent,slots,original){
    switch(intent){
      case 'create_task':return {type:'task.create',payload:{title:slots.task,due:slots.date}};
      case 'complete_task':return {type:'task.complete',payload:{title:slots.task}};
      case 'list_tasks':return {type:'task.list',payload:{}};
      case 'save_memory':return {type:'memory.save',payload:{content:slots.content}};
      case 'show_memory':return {type:'memory.list',payload:{}};
      case 'plan_day':case 'plan_tomorrow':return {type:'plan.create',payload:{scope:slots.date||'today'}};
      case 'inspect_project':return {type:'project.inspect',payload:{project:slots.project}};
      case 'github_status':return {type:'github.inspect',payload:{project:slots.project}};
      case 'help':return {type:'system.help',payload:{}};
      default:return {type:'system.unknown',payload:{original}};
    }
  }
  function understand(input){
    const text=normalize(input);
    if(!text)return {ok:false,intent:'unknown',confidence:0,slots:{},action:null,needsClarification:true,clarification:'What would you like Kyro to do?'};
    const ranked=rankIntents(text),top=ranked[0],second=ranked[1],confidence=confidenceFrom(top,second);
    if(!top||confidence<.56)return {ok:false,intent:'unknown',confidence,slots:{},action:null,needsClarification:true,clarification:'I understand the request only partially. Tell me the outcome you want.'};
    const slots={};
    if(top.id==='create_task'||top.id==='complete_task'){slots.task=extractTask(text,top.id);slots.date=extractDate(text)?.value||null;}
    if(top.id==='save_memory')slots.content=extractMemory(text);
    if(top.id==='inspect_project'||top.id==='github_status')slots.project=extractProject(text);
    if(top.id==='plan_tomorrow')slots.date='tomorrow';
    if(top.id==='plan_day')slots.date=/\btomorrow\b/i.test(text)?'tomorrow':'today';
    const errors=validate(top.id,slots);
    if(errors.length)return {ok:false,intent:top.id,confidence,slots,action:null,needsClarification:true,clarification:errors.includes('task')?'Which task do you mean?':'What exactly should I remember?'};
    return {ok:true,intent:top.id,confidence,slots,action:buildAction(top.id,slots,text),needsClarification:false,clarification:''};
  }
  function explain(result){
    if(!result)return 'No command was provided.';
    if(result.needsClarification)return result.clarification;
    return result.action?result.action.type+' '+JSON.stringify(result.action.payload):'I could not create an action for that request.';
  }
  return {version:'0.1.0',normalize,extractDate,understand,explain,intents:INTENTS.map(x=>x.id)};
});
