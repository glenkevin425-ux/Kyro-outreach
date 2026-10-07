const assert = require('assert');
const kyro = require('./command-engine');

const cases = [
  ['Add a task to study structural analysis tomorrow','create_task',{title:'study structural analysis',due:'tomorrow'}],
  ['Remind me to review Kcreatives today','create_task',{title:'review Kcreatives',due:'today'}],
  ['Remember that Kcreatives only offers Meta and TikTok ads','save_memory',{content:'Kcreatives only offers Meta and TikTok ads'}],
  ['Show my tasks','list_tasks',{}],
  ['What do you remember?','show_memory',{}],
  ['Plan my day','plan_day',{date:'today'}],
  ['Plan for tomorrow','plan_tomorrow',{date:'tomorrow'}],
  ['Review the Kcreatives project','inspect_project',{project:'Kcreatives'}],
  ['Check GitHub status','github_status',{project:null}],
  ['Help','help',{}]
];

for (const [input,intent,expected] of cases) {
  const result = kyro.understand(input);
  assert.strictEqual(result.ok,true,input);
  assert.strictEqual(result.intent,intent,input);
  for (const [key,value] of Object.entries(expected)) assert.deepStrictEqual(result.slots[key],value,input);
}

assert.strictEqual(kyro.understand('').needsClarification,true);
assert.strictEqual(kyro.understand('asdf qwerty zxcv').intent,'unknown');
assert.strictEqual(kyro.understand('Add a task').needsClarification,true);
assert.strictEqual(kyro.understand('Remember').needsClarification,true);

console.log('Kyro command engine tests passed:', cases.length + 4);
