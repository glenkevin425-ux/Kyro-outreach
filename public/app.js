(function () {
  'use strict';

  var KEY = 'kyro.v2';
  var VIEWS = [['dashboard','Dashboard'],['tasks','Tasks'],['projects','Projects'],['finance','Finance'],['ideas','Ideas'],['goals','Goals'],['activity','Activity']];
  var SPLIT = [['needs','Needs',14467],['savings','Savings',8177],['business','Business',5032],['other','Other',3774]];
  var SPLIT_TOTAL = 31450;
  var COLORS = {needs:'#1f5cff',savings:'#12a150',business:'#7c3aed',other:'#f59e0b'};

  var ICONS = {
    dashboard:'<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/><rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>',
    tasks:'<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/>',
    projects:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    finance:'<rect x="2" y="6" width="20" height="13" rx="3"/><path d="M2 11h20"/>',
    ideas:'<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
    goals:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
    activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>'
  };
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
  function money(n) { return 'KSh ' + Math.round(n).toLocaleString('en-US'); }
  function monthLabel(m) { var p = m.split('-'); return new Date(+p[0], +p[1] - 1, 1).toLocaleString('en-US', {month:'long', year:'numeric'}); }
  function thisMonth() { var d = new Date(); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2); }

  // Split any amount using the October ratios; remainder goes to Needs so the total is always exact.
  function allocate(amount) {
    var a = {}, used = 0;
    SPLIT.forEach(function (s) { a[s[0]] = Math.floor(amount * s[2] / SPLIT_TOTAL); used += a[s[0]]; });
    a.needs += amount - used;
    return a;
  }

  function seed() {
    return {
      v: 2, view: 'dashboard',
      tasks: [
        {id:'t1', title:'Review structural analysis', due:'Today', pri:'High', done:false},
        {id:'t2', title:'Work on Kcreatives homepage', due:'Today', pri:'High', done:false},
        {id:'t3', title:'Study for 2 hours', due:'Today', pri:'Medium', done:false},
        {id:'t4', title:'Review Kyro project roadmap', due:'Today', pri:'Medium', done:false},
        {id:'t5', title:'Send Golf Hotel proposal', due:'Tomorrow', pri:'High', done:false}
      ],
      projects: [
        {id:'p1', name:'Kcreatives', pct:82}, {id:'p2', name:'Kyro', pct:48},
        {id:'p3', name:'Fixly', pct:64}, {id:'p4', name:'MMUST HostelHub', pct:41}
      ],
      income: [
        {id:'i1', month:'2026-10', source:'October income', amount:31450,
         alloc:{needs:14467, savings:8177, business:5032, other:3774}}
      ],
      ideas: [
        {id:'d1', text:'Kcreatives client portal'}, {id:'d2', text:'Student command center'}
      ],
      goals: [
        {id:'g1', name:'Build Kcreatives into a consistent side business', pct:42},
        {id:'g2', name:'Maintain a strong university performance', pct:58},
        {id:'g3', name:'Build a 3-month emergency buffer', pct:31},
        {id:'g4', name:'Ship Kyro V1', pct:72}
      ],
      activity: [{id:'a1', text:'Kyro workspace created', at:Date.now()}]
    };
  }

  function valid(s) {
    return s && s.v === 2 && ['tasks','projects','income','ideas','goals','activity'].every(function (k) { return Array.isArray(s[k]); });
  }

  var state;
  var storageOK = true;
  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { var s = JSON.parse(raw); if (valid(s)) return s; }
    } catch (e) { storageOK = false; }
    return seed();
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); }
    catch (e) { if (storageOK) { storageOK = false; toast('Storage is unavailable. Changes will not survive a refresh.'); } }
  }

  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'toast'; t.textContent = msg;
    $('toasts').appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 2600);
  }
  function log(text) {
    state.activity.unshift({id:uid(), text:text, at:Date.now()});
    if (state.activity.length > 100) state.activity.length = 100;
  }
  function commit(msg, activity) {
    if (activity) log(activity);
    save(); render();
    if (msg) toast(msg);
  }

  /* ---------- views ---------- */
  function bar(p) { return '<div class="bar"><i style="width:' + p + '%"></i></div>'; }
  function taskRow(t) {
    return '<div class="row' + (t.done ? ' done' : '') + '">' +
      '<button class="chk" data-action="toggle-task" data-id="' + esc(t.id) + '" aria-label="Toggle task"></button>' +
      '<span class="t">' + esc(t.title) + '</span><span class="tag ' + esc(t.pri) + '">' + esc(t.pri) + '</span>' +
      '<span class="mut">' + esc(t.due) + '</span>' +
      '<button class="btn s" data-action="edit-task" data-id="' + esc(t.id) + '">Edit</button><button class="btn s d" data-action="del-task" data-id="' + esc(t.id) + '">Delete</button></div>';
  }
  function monthTotal(m) { return state.income.filter(function (i) { return i.month === m; }).reduce(function (a, i) { return a + i.amount; }, 0); }
  function monthAlloc(m) {
    var o = {needs:0, savings:0, business:0, other:0};
    state.income.forEach(function (i) { if (i.month === m) for (var k in o) o[k] += i.alloc[k]; });
    return o;
  }
  function months() {
    var seen = {}; state.income.forEach(function (i) { seen[i.month] = 1; });
    return Object.keys(seen).sort().reverse();
  }
  function avg(a) { return a.length ? Math.round(a.reduce(function (s, x) { return s + x.pct; }, 0) / a.length) : 0; }

  var RM = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var fx = $('fx'), cx = fx.getContext('2d'), parts = [], fxRaf = 0, enT = 0;
  function fxSize() { var d = window.devicePixelRatio || 1; fx.width = innerWidth * d; fx.height = innerHeight * d; cx.setTransform(d, 0, 0, d, 0, 0); }
  fxSize(); window.addEventListener('resize', fxSize);
  function fxTick() {
    cx.clearRect(0, 0, innerWidth, innerHeight);
    parts = parts.filter(function (p) { return p.l > 0; });
    parts.forEach(function (p) {
      p.vy += 0.35; p.vx *= 0.985; p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.l -= 0.011;
      cx.save(); cx.globalAlpha = Math.max(p.l, 0); cx.translate(p.x, p.y); cx.rotate(p.rot); cx.fillStyle = p.c;
      if (p.sq) cx.fillRect(-p.r, -p.r / 2, p.r * 2, p.r); else { cx.beginPath(); cx.arc(0, 0, p.r / 1.6, 0, 6.3); cx.fill(); }
      cx.restore();
    });
    fxRaf = parts.length ? requestAnimationFrame(fxTick) : 0;
    if (!parts.length) cx.clearRect(0, 0, innerWidth, innerHeight);
  }
  function burst(x, y, n) {
    if (RM) return;
    var C = ['#1d5bff', '#8b5cf6', '#06b6d4', '#10a25a', '#f59e0b', '#ff4d6d'];
    for (var i = 0; i < n; i++) {
      var a = Math.random() * 6.283, v = 3 + Math.random() * 10;
      parts.push({x:x, y:y, vx:Math.cos(a) * v, vy:Math.sin(a) * v - 6, r:3 + Math.random() * 5, rot:Math.random() * 6, vr:(Math.random() - 0.5) * 0.4, c:C[i % 6], l:1 + Math.random() * 0.4, sq:i % 2 === 0});
    }
    if (!fxRaf) fxRaf = requestAnimationFrame(fxTick);
  }
  function enter() {
    var m = $('main'); if (RM) return;
    Array.prototype.forEach.call(m.querySelectorAll('.hx,.head,.card,.row'), function (n, i) { n.style.setProperty('--i', i); });
    m.classList.add('enter'); clearTimeout(enT);
    enT = setTimeout(function () { m.classList.remove('enter'); }, 2200);
  }
  function pillTo() {
    var on = document.querySelector('.nav.on'), p = $('pill');
    if (on && p) { p.style.height = on.offsetHeight + 'px'; p.style.transform = 'translateY(' + on.offsetTop + 'px)'; }
  }
  function tagKpis() {
    Array.prototype.forEach.call(document.querySelectorAll('.kpi b:not([data-count])'), function (b) {
      var n = parseInt(b.textContent, 10);
      if (!isNaN(n)) { b.setAttribute('data-count', n); if (b.textContent.indexOf('%') > -1) b.setAttribute('data-suf', '%'); }
    });
  }
  function animBar(id, from, to) {
    var b = document.querySelector('[data-id="' + id + '"]'), row = b && b.closest('.row'), i = row ? row.querySelector('.bar i') : null;
    if (!i || RM) return;
    i.style.transition = 'none'; i.style.width = from + '%';
    requestAnimationFrame(function () { requestAnimationFrame(function () { i.style.transition = ''; i.style.width = to + '%'; }); });
  }
  var gx = 0, gy = 0, tx = 0, ty = 0, gr = 0;
  function glowTick() {
    gx += (tx - gx) * 0.12; gy += (ty - gy) * 0.12;
    $('glow').style.transform = 'translate(' + gx + 'px,' + gy + 'px)';
    gr = (Math.abs(tx - gx) + Math.abs(ty - gy) > 0.5) ? requestAnimationFrame(glowTick) : 0;
  }
  (function () {
    var el = $('intro'), seen = false; if (!el) return;
    try { seen = !!sessionStorage.getItem('kyro.intro'); sessionStorage.setItem('kyro.intro', '1'); } catch (e) {}
    if (seen || RM) { el.remove(); return; }
    setTimeout(function () { if (el.parentNode) el.remove(); }, 2300);
  })();

  function drawTabs() {
    var T = ['dashboard', 'tasks', 'projects', 'finance'], L = {dashboard:'Home', tasks:'Tasks', projects:'Projects', finance:'Finance'};
    var idx = T.indexOf(state.view); if (idx < 0) idx = 4;
    $('tabset').innerHTML = T.map(function (v) {
      return '<button class="tab' + (v === state.view ? ' on' : '') + '" data-view="' + v + '"><svg viewBox="0 0 24 24" aria-hidden="true">' + ICONS[v] + '</svg><span>' + L[v] + '</span></button>';
    }).join('') + '<button class="tab' + (idx === 4 ? ' on' : '') + '" data-action="menu"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg><span>More</span></button>';
    $('tpill').style.transform = 'translateX(' + idx * 100 + '%)';
  }
  try { if (localStorage.getItem('kyro.rail')) document.body.classList.add('rail'); } catch (e) {}
  try { if (document.fullscreenEnabled && $('fs')) $('fs').classList.add('ok'); } catch (e) {}
  var lastView = null;
  function ringsSvg(vals) {
    var R = [86, 68, 50, 32];
    return '<svg class="rings" viewBox="0 0 200 200" aria-hidden="true">' + vals.map(function (v, i) {
      var r = R[i], c = 2 * Math.PI * r;
      return '<circle class="trk" cx="100" cy="100" r="' + r + '"/><circle class="ring" cx="100" cy="100" r="' + r + '" stroke="' + v.c + '" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + c.toFixed(1) + '" data-to="' + (c * (1 - Math.min(1, v.p / 100))).toFixed(1) + '"/>';
    }).join('') + '</svg>';
  }
  function hero(cm) {
    var h = new Date().getHours(), g = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    var all = state.tasks.filter(function (t) { return t.due === 'Today'; });
    var dn = all.filter(function (t) { return t.done; }).length;
    var tp = all.length ? dn / all.length * 100 : 0, pp = avg(state.projects), gp = avg(state.goals);
    var tot = monthTotal(cm), a = monthAlloc(cm), ap = tot ? (a.needs + a.savings + a.business + a.other) / tot * 100 : 0;
    var mo = Math.round((tp + pp + gp) / 3);
    var L = [['Tasks today', tp, '#1d5bff'], ['Projects', pp, '#8b5cf6'], ['Goals', gp, '#06b6d4'], ['Allocated', ap, '#10a25a']];
    return '<section class="hx"><div><div class="hl">' + esc(new Date().toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric'})) + '</div>' +
      '<h2>' + g + '.<br>Here is your day.</h2><p>' + dn + ' of ' + all.length + ' tasks done today. Momentum blends tasks, projects and goals.</p>' +
      '<div class="chips"><button class="chip b" data-action="open-form" data-form="task">New task</button><button class="chip" data-action="open-form" data-form="income">Log income</button><button class="chip o" data-action="open-form" data-form="idea">Capture idea</button></div></div>' +
      '<div class="hxr"><div class="rw">' + ringsSvg(L.map(function (x) { return {p:x[1], c:x[2]}; })) +
      '<div class="mid"><b data-count="' + mo + '">' + mo + '</b><span>Momentum</span></div></div>' +
      '<div class="leg">' + L.map(function (x) { return '<div><i style="background:' + x[2] + '"></i>' + x[0] + '<b>' + Math.round(x[1]) + '%</b></div>'; }).join('') + '</div></div></section>';
  }
  function afterRender() {
    var fresh = lastView !== state.view; lastView = state.view;
    if (fresh) enter(); else $('main').classList.remove('enter');
    pillTo(); drawTabs();
    Array.prototype.forEach.call(document.querySelectorAll('.ring'), function (r) {
      if (fresh) requestAnimationFrame(function () { requestAnimationFrame(function () { r.style.strokeDashoffset = r.getAttribute('data-to'); }); });
      else { r.style.transition = 'none'; r.style.strokeDashoffset = r.getAttribute('data-to'); }
    });
    if (!fresh || RM) return;
    tagKpis();
    Array.prototype.forEach.call(document.querySelectorAll('[data-count]'), function (el) {
      var to = +el.getAttribute('data-count'), m = el.hasAttribute('data-money'), t0 = performance.now();
      function f(t) { var k = Math.min(1, (t - t0) / 900), v = Math.round(to * (1 - Math.pow(1 - k, 3))); el.textContent = m ? money(v) : v + (el.getAttribute('data-suf') || ''); if (k < 1) requestAnimationFrame(f); }
      requestAnimationFrame(f);
    });
  }

  var palSel = 0, palItems = [];
  function palList(q) {
    var all = VIEWS.map(function (v) { return {l:'Go to ' + v[1], run:function () { go(v[0]); }}; });
    [['task','Add task'],['project','Add project'],['income','Log income'],['idea','Capture idea'],['goal','Add goal']].forEach(function (a) {
      all.push({l:a[1], run:function () { openForm(a[0]); }});
    });
    q = q.toLowerCase();
    return all.filter(function (i) { return i.l.toLowerCase().indexOf(q) > -1; });
  }
  function palDraw(q) {
    palItems = palList(q); palSel = 0;
    $('pl').innerHTML = palItems.map(function (i, n) { return '<button class="pi' + (n === 0 ? ' on' : '') + '" data-pi="' + n + '">' + esc(i.l) + '</button>'; }).join('') || '<div class="empty">No matches</div>';
  }
  function openPal() {
    setMenu(false);
    $('pal').innerHTML = '<div class="psheet"><input id="pq" placeholder="Jump to a section or start an action" autocomplete="off" aria-label="Search"><div id="pl"></div></div>';
    $('pal').hidden = false; palDraw(''); $('pq').focus();
  }
  function closePal() { $('pal').hidden = true; $('pal').innerHTML = ''; }
  function palMove(d) {
    if (!palItems.length) return;
    palSel = (palSel + d + palItems.length) % palItems.length;
    Array.prototype.forEach.call(document.querySelectorAll('.pi'), function (b, n) { b.classList.toggle('on', n === palSel); if (n === palSel) b.scrollIntoView({block:'nearest'}); });
  }
  function palRun(n) { var it = palItems[n]; closePal(); if (it) it.run(); }

  var views = {
    dashboard: function () {
      var today = state.tasks.filter(function (t) { return t.due === 'Today' && !t.done; });
      var cm = months()[0] || thisMonth();
      return hero(cm) + '<div class="grid">' +
        '<div class="card kpi"><span>Open tasks today</span><b>' + today.length + '</b></div>' +
        '<div class="card kpi"><span>Average project progress</span><b>' + avg(state.projects) + '%</b></div>' +
        '<div class="card kpi"><span>' + esc(monthLabel(cm)) + ' income</span><b data-money="1" data-count="' + monthTotal(cm) + '">' + money(monthTotal(cm)) + '</b></div>' +
        '<div class="card kpi"><span>Average goal progress</span><b>' + avg(state.goals) + '%</b></div></div>' +
        '<div class="grid" style="margin-top:16px"><div class="card"><h3>Due today</h3>' +
        (today.length ? today.map(taskRow).join('') : '<div class="empty">Nothing left for today.</div>') + '</div>' +
        '<div class="card"><h3>Focus</h3><div class="focusline"><b>' + (state.tasks.filter(function(t){return !t.done;}).length) + '</b><span class="mut">open tasks</span></div><div class="focusline"><b>' + avg(state.goals) + '%</b><span class="mut">goal progress</span></div><div class="focusline"><b>' + avg(state.projects) + '%</b><span class="mut">project progress</span></div></div>' +
        '<div class="card"><h3>Projects</h3>' + state.projects.map(function (p) {
          return '<div class="row"><span class="t">' + esc(p.name) + '</span>' + bar(p.pct) + '<span class="mut">' + p.pct + '%</span></div>';
        }).join('') + '</div></div>';
    },
    tasks: function () {
      var open = state.tasks.filter(function (t) { return !t.done; }), done = state.tasks.filter(function (t) { return t.done; });
      return '<div class="head"><h2>Tasks</h2><button class="btn p" data-action="open-form" data-form="task">Add task</button></div>' +
        '<div class="card">' + (open.length ? open.map(taskRow).join('') : '<div class="empty">No open tasks. Add one to get started.</div>') + '</div>' +
        (done.length ? '<h3 class="mut" style="margin:20px 0 8px">Completed</h3><div class="card">' + done.map(taskRow).join('') + '</div>' : '');
    },
    projects: function () {
      return '<div class="head"><h2>Projects</h2><button class="btn p" data-action="open-form" data-form="project">Add project</button></div>' +
        '<div class="card">' + (state.projects.length ? state.projects.map(function (p) {
          return '<div class="row"><span class="t">' + esc(p.name) + '</span>' + bar(p.pct) + '<span class="mut">' + p.pct + '%</span>' +
            '<button class="btn s" data-action="adv-project" data-id="' + esc(p.id) + '"' + (p.pct >= 100 ? ' disabled' : '') + '>+10%</button>' +
            '<button class="btn s" data-action="edit-project" data-id="' + esc(p.id) + '">Edit</button>' +
            '<button class="btn s d" data-action="del-project" data-id="' + esc(p.id) + '">Delete</button></div>';
        }).join('') : '<div class="empty">No projects yet.</div>') + '</div>';
    },
    finance: function () {
      var ms = months();
      return '<div class="head"><h2>Finance</h2><button class="btn p" data-action="open-form" data-form="income">Log income</button></div>' +
        '<p class="mut" style="margin-top:-6px">Tracks income and how each shilling is allocated. Allocation always equals income.</p>' +
        (ms.length ? ms.map(function (m) {
          var total = monthTotal(m), a = monthAlloc(m);
          var sum = a.needs + a.savings + a.business + a.other;
          return '<div class="card" style="margin-bottom:16px"><div class="head"><h3 style="margin:0">' + esc(monthLabel(m)) + '</h3><b>' + money(total) + '</b></div>' +
            '<div class="seg">' + SPLIT.map(function (s) { return '<i style="width:' + (total ? a[s[0]] / total * 100 : 0) + '%;background:' + COLORS[s[0]] + '"></i>'; }).join('') + '</div>' +
            SPLIT.map(function (s) {
              return '<div class="row"><span style="width:10px;height:10px;border-radius:3px;background:' + COLORS[s[0]] + '"></span><span class="t">' + s[1] + '</span><b>' + money(a[s[0]]) + '</b></div>';
            }).join('') +
            '<div class="mut" style="margin-top:8px' + (sum === total ? '' : ';color:var(--bad)') + '">' + (sum === total ? 'Allocated in full: ' + money(sum) : 'Allocation mismatch') + '</div>' +
            state.income.filter(function (i) { return i.month === m; }).map(function (i) {
              return '<div class="row mut"><span class="t">' + esc(i.source) + '</span><span>' + money(i.amount) + '</span></div>';
            }).join('') + '</div>';
        }).join('') : '<div class="card empty">No income logged yet.</div>');
    },
    ideas: function () {
      return '<div class="head"><h2>Ideas</h2><button class="btn p" data-action="open-form" data-form="idea">Capture idea</button></div>' +
        '<div class="card">' + (state.ideas.length ? state.ideas.map(function (d) {
          return '<div class="row"><span class="t">' + esc(d.text) + '</span><button class="btn s d" data-action="del-idea" data-id="' + esc(d.id) + '">Delete</button></div>';
        }).join('') : '<div class="empty">No ideas captured yet.</div>') + '</div>';
    },
    goals: function () {
      return '<div class="head"><h2>Goals</h2><button class="btn p" data-action="open-form" data-form="goal">Add goal</button></div>' +
        '<div class="card">' + (state.goals.length ? state.goals.map(function (g) {
          return '<div class="row"><span class="t">' + esc(g.name) + '</span>' + bar(g.pct) + '<span class="mut">' + g.pct + '%</span>' +
            '<button class="btn s" data-action="adv-goal" data-id="' + esc(g.id) + '"' + (g.pct >= 100 ? ' disabled' : '') + '>+10%</button><button class="btn s" data-action="edit-goal" data-id="' + esc(g.id) + '">Edit</button></div>';
        }).join('') : '<div class="empty">No goals yet.</div>') + '</div>';
    },
    activity: function () {
      return '<div class="head"><h2>Activity</h2><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" data-action="export">Export backup</button><button class="btn" data-action="import">Import</button><button class="btn d" data-action="reset">Reset</button></div></div>' +
        '<div class="card">' + (state.activity.length ? state.activity.map(function (a) {
          return '<div class="row"><span class="t">' + esc(a.text) + '</span><span class="mut">' + esc(new Date(a.at).toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'})) + '</span></div>';
        }).join('') : '<div class="empty">No activity yet.</div>') + '</div>';
    }
  };

  function render() {
    if (!views[state.view]) state.view = 'dashboard';
    $('nav').innerHTML = VIEWS.map(function (v) {
      return '<button class="nav' + (v[0] === state.view ? ' on' : '') + '" data-view="' + v[0] + '"><svg viewBox="0 0 24 24" aria-hidden="true">' + ICONS[v[0]] + '</svg>' + v[1] + '</button>';
    }).join('');
    var label = VIEWS.filter(function (v) { return v[0] === state.view; })[0][1];
    $('title').textContent = label;
    try { $('main').innerHTML = views[state.view](); afterRender(); }
    catch (e) {
      console.error(e);
      $('main').innerHTML = '<div class="card err">This section failed to render. Open Activity and choose Reset demo data, or clear site data for this page.</div>';
    }
  }

  /* ---------- forms ---------- */
  function field(name, label, type, extra) { return '<label for="f-' + name + '">' + label + '</label><input id="f-' + name + '" name="' + name + '" type="' + type + '" ' + (extra || '') + '>'; }
  function select(name, label, opts, def) {
    return '<label for="f-' + name + '">' + label + '</label><select id="f-' + name + '" name="' + name + '">' +
      opts.map(function (o) { return '<option' + (o === def ? ' selected' : '') + '>' + o + '</option>'; }).join('') + '</select>';
  }
  var FORMS = {
    task: {title:'Add task', submit:'Add task', html: function (x) {
      return field('title', 'Task', 'text', 'required maxlength="120" autocomplete="off" value="' + esc(x && x.title || '') + '"') + select('due', 'Due', ['Today','Tomorrow','Later'], x && x.due || 'Today') + select('pri', 'Priority', ['High','Medium','Low'], x && x.pri || 'Medium');
    }, run: function (f, id) {
      var title = (f.get('title') || '').trim(); if (!title) return false;
      if (id) { var t = byId(state.tasks, id); if (!t) return false; t.title=title; t.due=f.get('due'); t.pri=f.get('pri'); commit('Task updated','Updated task: '+title); }
      else { state.tasks.unshift({id:uid(), title:title, due:f.get('due'), pri:f.get('pri'), done:false}); commit('Task added', 'Added task: ' + title); }
      return true;
    }},
    project: {title:'Add project', submit:'Add project', html: function (x) {
      return field('name', 'Name', 'text', 'required maxlength="80" autocomplete="off" value="' + esc(x && x.name || '') + '">') + field('pct', 'Progress (%)', 'number', 'min="0" max="100" value="' + (x ? x.pct : 0) + '"');
    }, run: function (f, id) {
      var name=(f.get('name')||'').trim(); if(!name) return false;
      var pct=Math.min(100,Math.max(0,parseInt(f.get('pct'),10)||0));
      if(id){var p=byId(state.projects,id);if(!p)return false;p.name=name;p.pct=pct;commit('Project updated','Updated project: '+name);}
      else{state.projects.push({id:uid(),name:name,pct:pct});commit('Project added','Added project: '+name);}
      return true;
    }},
    income: {title:'Log income', submit:'Log income', html: function () {
      return field('source', 'Source', 'text', 'required maxlength="80" autocomplete="off"') + field('amount', 'Amount (KSh)', 'number', 'required min="1" step="1" inputmode="numeric"') + field('month', 'Month', 'month', 'required value="' + thisMonth() + '"');
    }, run: function (f) {
      var amount=parseInt(f.get('amount'),10),source=(f.get('source')||'').trim(),month=f.get('month');
      if(!source||!(amount>0)||!/^\d{4}-\d{2}$/.test(month||''))return false;
      state.income.push({id:uid(),month:month,source:source,amount:amount,alloc:allocate(amount)});
      commit('Income logged','Logged '+money(amount)+' for '+monthLabel(month));return true;
    }},
    idea: {title:'Capture idea', submit:'Capture idea', html: function () {
      return field('text','Idea','text','required maxlength="160" autocomplete="off"');
    }, run: function (f) {
      var text=(f.get('text')||'').trim();if(!text)return false;
      state.ideas.unshift({id:uid(),text:text});commit('Idea captured','Captured idea: '+text);return true;
    }},
    goal: {title:'Add goal', submit:'Add goal', html: function (x) {
      return field('name','Goal','text','required maxlength="120" autocomplete="off" value="' + esc(x && x.name || '') + '">') + field('pct','Progress (%)','number','min="0" max="100" value="' + (x ? x.pct : 0) + '">');
    }, run: function (f,id) {
      var name=(f.get('name')||'').trim();if(!name)return false;
      var pct=Math.min(100,Math.max(0,parseInt(f.get('pct'),10)||0));
      if(id){var g=byId(state.goals,id);if(!g)return false;g.name=name;g.pct=pct;commit('Goal updated','Updated goal: '+name);}
      else{state.goals.push({id:uid(),name:name,pct:pct});commit('Goal added','Added goal: '+name);}
      return true;
    }}
  };

  function openForm(key, id) {
    var F = FORMS[key]; if (!F) return;
    var item = id ? byId(key === 'task' ? state.tasks : key === 'project' ? state.projects : state.goals, id) : null;
    var title = id ? 'Edit ' + (key === 'task' ? 'task' : key === 'project' ? 'project' : 'goal') : F.title;
    var submit = id ? 'Save changes' : F.submit;
    $('modal').innerHTML = '<div class="sheet" role="dialog" aria-modal="true" aria-label="' + title + '"><h2>' + title + '</h2>' +
      '<form data-form="' + key + '" data-edit-id="' + esc(id || '') + '" novalidate>' + F.html(item) +
      '<div class="acts"><button type="button" class="btn" data-action="close-modal">Cancel</button><button type="submit" class="btn p">' + submit + '</button></div></form></div>';
    $('modal').hidden = false;
    var first = $('modal').querySelector('input,select'); if (first) first.focus();
  }
  function closeModal() { $('modal').hidden = true; $('modal').innerHTML = ''; }
  function setMenu(open) { document.body.classList.toggle('menu', open); }
  function byId(list, id) { return list.filter(function (x) { return x.id === id; })[0]; }
  function drop(list, id) { var i = list.findIndex(function (x) { return x.id === id; }); if (i > -1) list.splice(i, 1); }

  /* ---------- actions ---------- */
  var ACTIONS = {
    'menu': function () { setMenu(!document.body.classList.contains('menu')); },
    'close-menu': function () { setMenu(false); },
    'open-form': function (el) { setMenu(false); openForm(el.dataset.form, el.dataset.id); },
    'close-modal': closeModal,
    'toggle-task': function (el) {
      var t = byId(state.tasks, el.dataset.id); if (!t) return;
      var rc = el.getBoundingClientRect(); t.done = !t.done; commit(t.done ? 'Task completed' : 'Task reopened', (t.done ? 'Completed: ' : 'Reopened: ') + t.title);
      if (t.done) { burst(rc.left + rc.width / 2, rc.top + rc.height / 2, 70); if (t.due === 'Today' && state.tasks.filter(function (x) { return x.due === 'Today'; }).every(function (x) { return x.done; })) burst(innerWidth / 2, innerHeight / 3, 220); }
    },
    'edit-task': function (el) { var t=byId(state.tasks,el.dataset.id); if(t) openForm('task',t.id); },
    'edit-project': function (el) { var p=byId(state.projects,el.dataset.id); if(p) openForm('project',p.id); },
    'edit-goal': function (el) { var g=byId(state.goals,el.dataset.id); if(g) openForm('goal',g.id); },
    'del-task': function (el) { var t = byId(state.tasks, el.dataset.id); if (t) { drop(state.tasks, t.id); commit('Task deleted', 'Deleted task: ' + t.title); } },
    'adv-project': function (el) {
      var p = byId(state.projects, el.dataset.id); if (!p) return;
      var o = p.pct; p.pct = Math.min(100, p.pct + 10); commit('Progress updated', p.name + ' is now at ' + p.pct + '%');
      animBar(p.id, o, p.pct); if (p.pct >= 100) burst(innerWidth / 2, innerHeight / 3, 200);
    },
    'del-project': function (el) { var p = byId(state.projects, el.dataset.id); if (p) { drop(state.projects, p.id); commit('Project deleted', 'Deleted project: ' + p.name); } },
    'del-idea': function (el) { var d = byId(state.ideas, el.dataset.id); if (d) { drop(state.ideas, d.id); commit('Idea deleted', 'Deleted idea: ' + d.text); } },
    'adv-goal': function (el) {
      var g = byId(state.goals, el.dataset.id); if (!g) return;
      var o = g.pct; g.pct = Math.min(100, g.pct + 10); commit('Progress updated', g.name + ' is now at ' + g.pct + '%');
      animBar(g.id, o, g.pct); if (g.pct >= 100) burst(innerWidth / 2, innerHeight / 3, 200);
    },
    'palette': openPal,
    'fullscreen': function () { if (document.fullscreenElement) { document.exitFullscreen(); return; } var r = document.documentElement.requestFullscreen ? document.documentElement.requestFullscreen() : null; if (r && r.catch) r.catch(function () { toast('Full screen is not available here'); }); setMenu(false); },
    'rail': function () {
      var on = document.body.classList.toggle('rail');
      try { localStorage.setItem('kyro.rail', on ? '1' : ''); } catch (e) {}
      setTimeout(pillTo, 330);
    },
    'export': function () {
      var b = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'}), a = document.createElement('a');
      a.href = URL.createObjectURL(b); a.download = 'kyro-backup-' + new Date().toISOString().slice(0, 10) + '.json';
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 500); toast('Backup downloaded');
    },
    'import': function () { $('imp').click(); },
    'reset': function () {
      if (!window.confirm('Replace all data with the demo data?')) return;
      state = seed(); save(); render(); toast('Demo data restored');
    }
  };

  function go(view) { state.view = view; setMenu(false); save(); render(); window.scrollTo(0, 0); }

  // One delegated listener per event type. A failing handler is contained and cannot disable the others.
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('[data-view],[data-action]') : null;
    if (e.target.id === 'modal') { closeModal(); return; }
    if (e.target.id === 'pal') { closePal(); return; }
    var pi = e.target.closest ? e.target.closest('[data-pi]') : null;
    if (pi) { palRun(+pi.getAttribute('data-pi')); return; }
    if (!el) return;
    try {
      if (!RM && navigator.vibrate && 'ontouchstart' in window) navigator.vibrate(8);
      if (el.dataset.view) go(el.dataset.view);
      else if (ACTIONS[el.dataset.action]) ACTIONS[el.dataset.action](el);
    } catch (err) { console.error(err); toast('Something went wrong. Please try again.'); }
  });
  document.addEventListener('submit', function (e) {
    var f = e.target.closest ? e.target.closest('form[data-form]') : null;
    if (!f) return;
    e.preventDefault();
    try {
      var F = FORMS[f.dataset.form];
      if (F && F.run(new FormData(f), f.dataset.editId || '')) closeModal(); else toast('Please fill in every field correctly.');
    } catch (err) { console.error(err); toast('Could not save. Please try again.'); }
  });
  document.addEventListener('keydown', function (e) {
    var tg = (e.target && e.target.tagName) || '';
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if ($('pal').hidden) openPal(); else closePal(); return; }
    if (!$('pal').hidden) {
      if (e.key === 'Escape') { closePal(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); palMove(e.key === 'ArrowDown' ? 1 : -1); return; }
      if (e.key === 'Enter') { e.preventDefault(); palRun(palSel); }
      return;
    }
    if (e.key === 'Escape') { closeModal(); setMenu(false); return; }
    if ((e.key >= '1' && e.key <= '7') && !e.metaKey && !e.ctrlKey && !e.altKey && $('modal').hidden && !/INPUT|SELECT|TEXTAREA/.test(tg)) { go(VIEWS[+e.key - 1][0]); return; }
    if ((e.key === 'n' || e.key === 'N') && !e.metaKey && !e.ctrlKey && !e.altKey && $('modal').hidden && !/INPUT|SELECT|TEXTAREA/.test(tg)) { e.preventDefault(); openForm('task'); }
  });
  document.addEventListener('pointermove', function (e) {
    if (RM) return;
    tx = e.clientX; ty = e.clientY; if (!gr) gr = requestAnimationFrame(glowTick);
    var h = e.target.closest ? e.target.closest('.hx') : null;
    if (h) {
      var r = h.getBoundingClientRect();
      h.style.setProperty('--ry', ((e.clientX - r.left) / r.width - 0.5) * 9 + 'deg');
      h.style.setProperty('--rx', (0.5 - (e.clientY - r.top) / r.height) * 9 + 'deg');
    }
    var b = e.target.closest ? e.target.closest('.btn.p,.chip') : null;
    if (b) { var q = b.getBoundingClientRect(); b.style.transform = 'translate(' + ((e.clientX - q.left - q.width / 2) * 0.22) + 'px,' + ((e.clientY - q.top - q.height / 2) * 0.3) + 'px)'; }
  });
  document.addEventListener('pointerout', function (e) {
    var t = e.target.closest ? e.target.closest('.hx,.btn.p,.chip') : null;
    if (!t || t.contains(e.relatedTarget)) return;
    if (t.classList.contains('hx')) { t.style.setProperty('--rx', '0deg'); t.style.setProperty('--ry', '0deg'); } else t.style.transform = '';
  });
  document.addEventListener('input', function (e) { if (e.target.id === 'pq') palDraw(e.target.value); });
  var sheetEl = null, sy = 0, sdy = 0;
  document.addEventListener('touchstart', function (e) {
    var sh = e.target.closest ? e.target.closest('.sheet') : null;
    if (!sh || innerWidth > 820 || e.touches[0].clientY - sh.getBoundingClientRect().top > 56) return;
    sheetEl = sh; sy = e.touches[0].clientY; sdy = 0; sh.style.animation = 'none'; sh.style.transition = 'none';
  }, {passive:true});
  document.addEventListener('touchmove', function (e) {
    if (!sheetEl) return;
    sdy = Math.max(0, e.touches[0].clientY - sy); sheetEl.style.transform = 'translateY(' + sdy + 'px)';
  }, {passive:true});
  document.addEventListener('touchend', function () {
    if (!sheetEl) return;
    var sh = sheetEl; sheetEl = null;
    if (sdy > 100) closeModal(); else { sh.style.transition = 'transform .3s cubic-bezier(.2,.8,.2,1)'; sh.style.transform = ''; }
  });
  document.addEventListener('pointermove', function (e) {
    var c = e.target.closest ? e.target.closest('.card') : null;
    if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px'); c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  });
  document.addEventListener('change', function (e) {
    if (e.target.id !== 'imp' || !e.target.files[0]) return;
    var inp = e.target, rd = new FileReader();
    rd.onload = function () {
      try { var d = JSON.parse(rd.result); if (!valid(d)) throw new Error('bad'); state = d; log('Imported a backup'); save(); render(); toast('Backup restored'); }
      catch (x) { toast('That file is not a valid Kyro backup.'); }
      inp.value = '';
    };
    rd.readAsText(inp.files[0]);
  });

  state = load();
  render();
})();
