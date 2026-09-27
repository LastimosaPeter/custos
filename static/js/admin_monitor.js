(function(){
  'use strict';
  const page=document.querySelector('.monitor-page'); if(!page) return;
  const list=document.getElementById('monitorStudentList');
  const filter=document.getElementById('monitorFilter');
  const updated=document.getElementById('monitorUpdated');
  const csrf=document.querySelector('meta[name="csrf-token"]')?.content||'';
  const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const name=s=>(s.last_name||s.first_name)?`${s.last_name||''}${s.last_name&&s.first_name?', ':''}${s.first_name||''}`:(s.student_name||s.email);
  function visible(level){const f=filter.value;return f==='all'||f===level||(f==='attention'&&(level==='high'||level==='locked'));}
  function render(students){
    document.getElementById('monitorActive').textContent=students.length;
    document.getElementById('monitorAttention').textContent=students.filter(s=>s.attention_level==='high'||s.attention_level==='locked').length;
    document.getElementById('monitorLocked').textContent=students.filter(s=>s.attention_level==='locked').length;
    const shown=students.filter(s=>visible(s.attention_level));
    if(!shown.length){list.innerHTML='<div class="monitor-empty">No active students match this view.</div>';return;}
    list.innerHTML=shown.map(s=>`<article class="monitor-student-card attention-${esc(s.attention_level)}" data-level="${esc(s.attention_level)}" data-session-id="${Number(s.id)}">
      <div class="monitor-card-top"><div><strong>${esc(name(s))}</strong><span>${esc(s.program||'—')} ${esc(s.class_section||'')} · ${esc(s.batch_name)}</span></div><span class="monitor-attention-badge ${esc(s.attention_level)}">${esc(s.attention_label)}</span></div>
      <div class="monitor-card-metrics"><div><span>Violations</span><strong>${Number(s.violation_count||0)}/3</strong></div><div><span>Flags</span><strong>${Number(s.flagged_count||0)}</strong></div><div><span>Answered</span><strong>${Number(s.answered||0)}/${Number(s.total||0)}</strong></div><div><span>Chat</span><strong>${Number(s.unread_messages||0)}</strong></div></div>
      <div class="monitor-last-event"><span>Latest event</span><strong>${esc((s.last_event||'No event yet').replaceAll('_',' '))}</strong>${s.last_event_detail?`<small>${esc(s.last_event_detail)}</small>`:''}</div>
      <div class="monitor-card-actions">${s.security_locked||s.pending_blackout?'<button type="button" class="secondary monitor-action-btn" data-monitor-action="clear_security">Clear Lock</button>':''}<a class="secondary button-link" href="/admin/messages?session=${Number(s.id)}">Message</a><button type="button" class="secondary monitor-action-btn" data-monitor-action="mark_done">Mark Done</button><a class="primary button-link" href="/admin/session/${Number(s.id)}">Review Student</a></div>
    </article>`).join('');
  }
  async function refresh(){
    try{const r=await fetch(page.dataset.monitorEndpoint,{headers:{'Accept':'application/json'},cache:'no-store'});const data=await r.json();if(data.ok){render(data.students||[]);updated.textContent='Updated just now';}}
    catch(e){updated.textContent='Refresh failed';}
  }
  async function doAction(card,action){
    const sid=Number(card?.dataset.sessionId||0); if(!sid)return;
    const prompt=action==='mark_done'?'Mark this student as done in Live Monitor? This does not submit or change answers.':'Clear the active security lock? Recorded violations will remain.';
    if(!window.confirm(prompt))return;
    try{
      const r=await fetch(`/admin/monitor/session/${sid}/action`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({action})});
      const data=await r.json(); if(data.ok) await refresh(); else window.alert(data.error||'Could not update session.');
    }catch(e){window.alert('Could not update session.');}
  }
  list.addEventListener('click',e=>{const b=e.target.closest('[data-monitor-action]');if(b){e.preventDefault();doAction(b.closest('[data-session-id]'),b.dataset.monitorAction);}});
  filter.addEventListener('change',refresh); document.getElementById('monitorRefresh').addEventListener('click',refresh);
  setInterval(refresh,10000);
})();
