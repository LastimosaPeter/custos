(() => {
  'use strict';
  const app = document.getElementById('ideApp');
  if (!app) return;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const panels = [...document.querySelectorAll('.ide-task-panel')];
  const taskButtons = [...document.querySelectorAll('.ide-task-button')];
  const taskNav = document.getElementById('ideTaskNav');
  const taskBackdrop = document.getElementById('ideTaskBackdrop');
  const taskToggle = document.getElementById('ideTaskNavToggle');
  const taskClose = document.getElementById('ideTaskNavClose');
  const saveBtn = document.getElementById('ideSaveBtn');
  const runBtn = document.getElementById('ideRunBtn');
  const submitTaskBtn = document.getElementById('ideSubmitTaskBtn');
  const finishBtn = document.getElementById('ideFinishBtn');
  const finishOverlay = document.getElementById('ideFinishOverlay');
  const cancelFinish = document.getElementById('ideCancelFinish');
  const finishForm = document.getElementById('ideFinishForm');
  const saveState = document.getElementById('ideSaveState');
  const timer = document.getElementById('ideTimer');
  const currentTaskLabel = document.getElementById('ideCurrentTaskLabel');
  const secureOverlay = document.getElementById('ideSecureOverlay');
  const enterSecure = document.getElementById('ideEnterSecure');
  const secureError = document.getElementById('ideSecureError');
  const lockOverlay = document.getElementById('ideLockOverlay');
  const lockTitle = document.getElementById('ideLockTitle');
  const lockCountdown = document.getElementById('ideLockCountdown');
  const lockMessage = document.getElementById('ideLockMessage');
  const violationCount = document.getElementById('ideViolationCount');
  const violationMini = document.getElementById('ideViolationMini');
  const resumeSecure = document.getElementById('ideResumeSecure');
  const inactiveOverlay = document.getElementById('ideInactiveOverlay');
  const stillHere = document.getElementById('ideStillHere');

  let current = 0;
  let secureEntered = false;
  let intentionalNavigation = false;
  let violationInFlight = false;
  let remaining = app.dataset.remaining === '' ? null : Number(app.dataset.remaining || 0);
  let saveTimer = null;
  let tempLockEnds = 0;
  let lastActivity = Date.now();
  let inactivityShown = false;
  let state = {
    violationCount: Number(app.dataset.violationCount || 0),
    permanent: app.dataset.securityLocked === '1',
    pending: app.dataset.pendingBlackout === '1',
    tempRemaining: Number(app.dataset.tempLockRemaining || 0)
  };

  const installed = () => window.matchMedia('(display-mode: standalone)').matches || window.matchMedia('(display-mode: fullscreen)').matches || navigator.standalone === true;
  const secureActive = () => installed() || Boolean(document.fullscreenElement);
  const post = (url, payload) => fetch(url, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(payload),credentials:'same-origin',keepalive:true});
  const log = (type, detail='') => post('/api/ide/event',{type,detail}).catch(()=>{});

  function panelData(panel = panels[current]) {
    return {
      task_id: Number(panel.dataset.taskId),
      source_code: panel.querySelector('.ide-code-editor').value,
      stdin_text: panel.querySelector('.ide-stdin').value
    };
  }

  function setTask(index) {
    current = Math.max(0, Math.min(index, panels.length - 1));
    panels.forEach((p,i)=>p.classList.toggle('hidden',i!==current));
    taskButtons.forEach((b,i)=>b.classList.toggle('active',i===current));
    currentTaskLabel.textContent = `Task ${current + 1}`;
    updateLineNumbers();
    if (window.innerWidth <= 1024) setTaskNav(false);
    saveCurrent(false);
  }
  taskButtons.forEach((b,i)=>b.addEventListener('click',()=>setTask(i)));
  function setTaskNav(open) { taskNav.classList.toggle('mobile-open',open); taskBackdrop.classList.toggle('active',open); }
  taskToggle?.addEventListener('click',()=>setTaskNav(true)); taskClose?.addEventListener('click',()=>setTaskNav(false)); taskBackdrop?.addEventListener('click',()=>setTaskNav(false));

  function updateLineNumbers(panel=panels[current]) {
    if (!panel) return;
    const editor = panel.querySelector('.ide-code-editor');
    const gutter = panel.querySelector('.ide-line-numbers');
    const count = Math.max(1, editor.value.split('\n').length);
    gutter.textContent = Array.from({length:count},(_,i)=>i+1).join('\n');
    gutter.scrollTop = editor.scrollTop;
  }
  document.querySelectorAll('.ide-code-editor').forEach(editor=>{
    editor.addEventListener('input',()=>{ updateLineNumbers(editor.closest('.ide-task-panel')); scheduleSave(); });
    editor.addEventListener('scroll',()=>{ const gutter=editor.closest('.ide-task-panel').querySelector('.ide-line-numbers'); gutter.scrollTop=editor.scrollTop; });
    editor.addEventListener('keydown',e=>{
      if (e.key === 'Tab') { e.preventDefault(); const s=editor.selectionStart, end=editor.selectionEnd; editor.setRangeText('    ',s,end,'end'); scheduleSave(); updateLineNumbers(editor.closest('.ide-task-panel')); }
    });
  });
  document.querySelectorAll('.ide-stdin').forEach(x=>x.addEventListener('input',scheduleSave));

  function scheduleSave(){ saveState.textContent='Unsaved'; clearTimeout(saveTimer); saveTimer=setTimeout(()=>saveCurrent(),700); }
  async function saveCurrent(show=true){
    if (!panels[current]) return;
    if(show) saveState.textContent='Saving…';
    try { const res=await post('/api/ide/save',panelData()); const data=await res.json(); if(res.status===423){applySecurity(data);return;} if(!res.ok) throw new Error(); saveState.textContent='Saved'; }
    catch(_){ saveState.textContent='Save failed'; }
  }
  saveBtn.addEventListener('click',()=>saveCurrent());

  function renderRun(panel,data){
    const result=data.result||{}; panel.querySelector('.ide-output').textContent=result.stdout || result.stderr || result.compile_output || 'Program finished with no output.';
    panel.querySelector('.js-output-status').textContent=result.status||'Finished'; panel.querySelector('.js-task-status').textContent=result.status||'Finished';
    const runs=panel.querySelector('.js-run-count'); runs.textContent=String(Number(runs.textContent||0)+1);
  }
  runBtn.addEventListener('click',async()=>{
    const panel=panels[current]; await saveCurrent(false); runBtn.disabled=true; runBtn.textContent='Running…'; panel.querySelector('.ide-output').textContent='Compiling and running…';
    try { const res=await post('/api/ide/run',panelData(panel)); const data=await res.json(); if(res.status===423){applySecurity(data);return;} if(!res.ok){panel.querySelector('.ide-output').textContent=data.error||'Runner error.';return;} renderRun(panel,data); }
    catch(_){panel.querySelector('.ide-output').textContent='Could not reach the code runner.';} finally {runBtn.disabled=false;runBtn.textContent='Run Code';}
  });
  submitTaskBtn.addEventListener('click',async()=>{
    const panel=panels[current]; await saveCurrent(false); submitTaskBtn.disabled=true; submitTaskBtn.textContent='Testing…';
    try { const payload=panelData(panel); const res=await post('/api/ide/submit-task',{task_id:payload.task_id,source_code:payload.source_code}); const data=await res.json(); if(res.status===423){applySecurity(data);return;} if(!res.ok){panel.querySelector('.ide-output').textContent=data.error||'Submission failed.';return;} panel.querySelector('.js-task-status').textContent=data.status; panel.querySelector('.js-output-status').textContent=`${data.passed}/${data.total} hidden tests`; panel.querySelector('.ide-output').textContent=`Hidden tests: ${data.passed}/${data.total} passed\nScore: ${data.score}/${panel.dataset.points}`; taskButtons[current].querySelector('small').textContent=`${data.score}/${panel.dataset.points} pts · ${data.status}`; }
    catch(_){panel.querySelector('.ide-output').textContent='Submission request failed.';} finally {submitTaskBtn.disabled=false;submitTaskBtn.textContent='Submit Task';}
  });

  finishBtn.addEventListener('click',()=>finishOverlay.classList.add('active')); cancelFinish.addEventListener('click',()=>finishOverlay.classList.remove('active')); finishForm.addEventListener('submit',()=>{intentionalNavigation=true;});

  async function enterSecureMode(){
    secureError.classList.add('hidden');
    try { if(installed()){secureEntered=true;secureOverlay.classList.remove('active');log('standalone_secure_mode_enter','Installed Custos IDE secure mode entered');return;} if(!document.fullscreenElement) await document.documentElement.requestFullscreen(); secureEntered=true;secureOverlay.classList.remove('active');log('fullscreen_enter','IDE fullscreen entered'); }
    catch(_){secureError.classList.remove('hidden');}
  }
  enterSecure.addEventListener('click',enterSecureMode); resumeSecure.addEventListener('click',enterSecureMode);

  function applySecurity(data){ state.violationCount=Number(data.violation_count??state.violationCount);state.permanent=Boolean(data.permanent);state.pending=Boolean(data.pending);state.tempRemaining=Number(data.temp_remaining??0);renderSecurity(); }
  function renderSecurity(){
    violationCount.textContent=state.violationCount; violationMini.textContent=`${state.violationCount}/3 violations`;
    if(state.permanent){lockOverlay.classList.add('active','permanent');lockTitle.textContent='Coding Session Locked';lockCountdown.textContent='INSTRUCTOR REQUIRED';lockMessage.textContent='Three security violations were recorded. Only your instructor can unlock the IDE.';resumeSecure.classList.add('hidden');return;}
    lockOverlay.classList.remove('permanent');
    if(state.pending){lockOverlay.classList.add('active');lockTitle.textContent='Security Event Detected';lockCountdown.textContent='…';lockMessage.textContent='The 15-second lock begins when Custos regains focus.';resumeSecure.classList.add('hidden');return;}
    if(state.tempRemaining>0){tempLockEnds=Date.now()+state.tempRemaining*1000;lockOverlay.classList.add('active');lockTitle.textContent='Security Lock';lockMessage.textContent='The IDE is temporarily unavailable. Your lab timer continues.';resumeSecure.classList.add('hidden');return;}
    if(secureEntered&&!secureActive()){lockOverlay.classList.add('active');lockTitle.textContent='Security Lock Complete';lockCountdown.textContent='READY';lockMessage.textContent='Return to secure display mode to continue.';resumeSecure.classList.remove('hidden');} else {lockOverlay.classList.remove('active');resumeSecure.classList.add('hidden');}
  }
  async function violation(source){ if(!secureEntered||intentionalNavigation||state.permanent||state.pending||state.tempRemaining>0||violationInFlight)return; violationInFlight=true; try{const res=await post('/api/ide/security-violation',{source});const data=await res.json();if(data.ok){applySecurity(data);if(state.pending&&!document.hidden&&document.hasFocus()) await startLock();}}catch(_){}finally{violationInFlight=false;} }
  async function startLock(){try{const res=await post('/api/ide/security-start-lock',{});const data=await res.json();if(data.ok)applySecurity(data);}catch(_){}}
  async function refreshSecurity(){try{const res=await fetch('/api/ide/security-status',{credentials:'same-origin',cache:'no-store'});const data=await res.json();if(data.ok){applySecurity(data);if(state.pending&&!document.hidden&&document.hasFocus())await startLock();}}catch(_){}}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)violation('visibility_hidden');else refreshSecurity();});
  window.addEventListener('blur',()=>violation('window_blur'));
  document.addEventListener('fullscreenchange',()=>{if(secureEntered&&!installed()&&!document.fullscreenElement)violation('fullscreen_exit');});
  document.addEventListener('contextmenu',e=>{e.preventDefault();log('contextmenu','Right-click blocked in secure IDE');});
  document.addEventListener('keydown',e=>{const key=e.key.toLowerCase();if((e.ctrlKey||e.metaKey)&&['u','s','p'].includes(key) || key==='f12' || (e.ctrlKey&&e.shiftKey&&['i','j','c'].includes(key))){e.preventDefault();log('blocked_shortcut',`Blocked shortcut ${e.key}`);}});

  function activity(){ lastActivity=Date.now(); if(inactivityShown){inactivityShown=false;inactiveOverlay.classList.remove('active');} }
  ['mousemove','mousedown','keydown','touchstart','scroll','input'].forEach(type=>document.addEventListener(type,activity,{passive:true}));
  stillHere?.addEventListener('click',activity);
  setInterval(()=>{if(secureEntered&&!inactivityShown&&Date.now()-lastActivity>=60000){inactivityShown=true;inactiveOverlay.classList.add('active');log('inactivity','No IDE activity detected for 60 seconds');}},5000);

  if(remaining!==null){setInterval(()=>{remaining=Math.max(0,remaining-1);const h=String(Math.floor(remaining/3600)).padStart(2,'0'),m=String(Math.floor((remaining%3600)/60)).padStart(2,'0'),s=String(remaining%60).padStart(2,'0');timer.textContent=`${h}:${m}:${s}`;if(remaining===0){intentionalNavigation=true;finishForm.submit();}},1000);}
  setInterval(()=>{if(state.tempRemaining>0&&tempLockEnds){state.tempRemaining=Math.max(0,Math.ceil((tempLockEnds-Date.now())/1000));lockCountdown.textContent=String(state.tempRemaining);if(state.tempRemaining===0)refreshSecurity();}},250);
  setInterval(()=>{if(!document.hidden)refreshSecurity();},5000);
  window.addEventListener('beforeunload',()=>{if(!intentionalNavigation) log('beforeunload','Programming Lab page unloading');});
  panels.forEach(p=>updateLineNumbers(p)); renderSecurity();
})();
