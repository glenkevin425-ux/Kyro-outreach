// Usage: node scripts/check.js
// Dependency-free static checks for Kyro's plain HTML/CSS/JS app.
var fs = require('fs');
var vm = require('vm');
var assert = require('assert');
var html = fs.readFileSync('public/index.html', 'utf8');
var app = fs.readFileSync('public/app.js', 'utf8');
var css = fs.readFileSync('public/styles.css', 'utf8');

function check(condition, message) {
  assert.ok(condition, message);
  console.log('PASS ' + message);
}

try {
  new vm.Script(app, { filename: 'public/app.js' });
  console.log('PASS JavaScript syntax');
} catch (error) {
  console.error('FAIL JavaScript syntax: ' + error.message);
  process.exit(1);
}

check(/href=["']styles\.css["']/.test(html) && /src=["']app\.js["']/.test(html), 'HTML links the expected local assets');
check(!/\bonclick\s*=/i.test(html + app), 'no inline onclick handlers');
check(html.indexOf('Content-Security-Policy') !== -1, 'baseline Content Security Policy exists');
check(html.indexOf('fonts.googleapis.com') === -1 && css.indexOf('fonts.googleapis.com') === -1, 'no external Google Fonts dependency');
check(app.indexOf("var KEY = 'kyro.v2'") !== -1, 'local-first storage key remains stable');
check(app.indexOf("v: 3, view: 'dashboard'") !== -1 && app.indexOf("function removeWithUndo") !== -1, 'version 3 state and undo support exist');
check(app.indexOf('function checkBackupReminder') !== -1, 'backup reminder exists');
check(app.indexOf("focusables = $('modal').querySelectorAll") !== -1, 'modal keyboard focus trap exists');
check(css.indexOf('@media(prefers-reduced-motion:reduce)') !== -1 || css.indexOf('@media (prefers-reduced-motion: reduce)') !== -1, 'reduced-motion styling exists');

var split = app.match(/var SPLIT = \[\['needs','Needs',(\d+)\],\['savings','Savings',(\d+)\],\['business','Business',(\d+)\],\['other','Other',(\d+)\]\];/);
check(!!split, 'finance allocation constants exist');
var amounts = split.slice(1).map(Number);
check(amounts.reduce(function (sum, n) { return sum + n; }, 0) === 31450, 'finance allocation sums to KSh 31,450');
check(amounts.join(',') === '14467,8177,5032,3774', 'October allocation matches the project invariant');

var october = app.match(/month:'2026-10', source:'October income', amount:31450,\s*alloc:\{needs:14467, savings:8177, business:5032, other:3774\}/);
check(!!october, 'October demo income matches the allocation invariant');

console.log('Kyro checks passed.');
