const assert = require('assert');
const kyro = require('./command-engine');

const cases = [
  ['Add a task to study structural analysis tomorrow','create_task',{task:'study structural analysis',date:'tomorrow'}],
  ['Remind me to review Kcreatives today','create_task',{task:'review Kcreatives',date:'today'}],
  ['Remember that Kcreatives only offers Meta and TikTok ads','save_memory',{content:'Kcreatives only offers Meta and TikTok ads'}],
  ['Show my tasks','list_tasks',{}],
  ['What do you remember?','show_memory',{}],
  ['Plan my day','plan_day',{date:'today'}],
  ['Plan for tomorrow','plan_tomorrow',{date:'tomorrow'}],
  ['Review the Kcreatives project','inspect_project',{project:'Kcreatives'}],
  ['Check GitHub status','github_status',{project:null}],
  ['Delete the task called study structural analysis','delete_task',{task:'the task called study structural analysis'}],
  ['Edit task study structural analysis tomorrow at 7pm high priority','edit_task',{task:'study structural analysis',date:'tomorrow',time:'19:00',priority:'high'}],
  ['Find information about structural engineering','search',{query:'information about structural engineering'}],
  ['Save this idea: build a client portal','add_idea',{idea:'this idea: build a client portal'}],
  ['Start a focus session for 45 minutes','start_focus',{duration:45}],
  ['Stop my focus session','stop_focus',{}],
  ['Open the Kcreatives project','open_project',{project:'Kcreatives'}],
  ['Help','help',{}]
];

for(const [input,intent,expected] of cases){
  const result=kyro.understand(input);
  assert.strictEqual(result.ok,true,input);
  assert.strictEqual(result.intent,intent,input);
  for(const [key,value] of Object.entries(expected)) assert.deepStrictEqual(result.slots[key],value,input);
}

assert.strictEqual(kyro.understand('').needsClarification,true);
assert.strictEqual(kyro.understand('asdf qwerty zxcv').intent,'unknown');
assert.strictEqual(kyro.understand('Add a task').needsClarification,true);
assert.strictEqual(kyro.understand('Remember').needsClarification,true);
assert.strictEqual(kyro.understand('Start a focus session').needsClarification,true);

console.log('Kyro command engine regression cases:',cases.length+5);
