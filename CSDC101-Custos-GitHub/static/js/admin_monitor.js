(function(){
  const page=document.querySelector('.monitor-page'); if(!page) return;
  const list=document.getElementById('monitorStudentList');
  const filter=document.getElementById('monitorFilter');
  const updated=document.getElementById('monitorUpdated');
  const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  function visible(level){const f=filter.value;return f==='all'||f===level||(f==='attention'&&(level==='high'||level==='locked'));}
  function render(students){
    document.getElementById('monitorActive').textContent=students.length;
    document.getElementById('monitorAttention').textContent=students.filter(s=>s.attention_level==='high'||s.attention_level==='locked').length;
    document.getElementById('monitorLocked').textContent=students.filter(s=>s.attention_level==='locked').length;
    const shown=students.filter(s=>visible(s.attention_level));
    if(!shown.length){list.innerHTML='<div class="monitor-empty">No active students match this view.</div>';return;}
    list.innerHTML=shown.map(s=>`<article class="monitor-student-card attention-${esc(s.attention_level)}" data-level="${esc(s.attention_level)}">
      <div class="monitor-card-top"><div><strong>${esc(s.student_name||s.email)}</strong><span>${esc(s.program||'—')} ${esc(s.class_section||'')} · ${esc(s.batch_name)}</span></div><span class="monitor-attention-badge ${esc(s.attention_level)}">${esc(s.attention_label)}</span></div>
      <div class="monitor-card-metrics"><div><span>Violations</span><strong>${Number(s.violation_count||0)}/3</strong></div><div><span>Flags</span><strong>${Number(s.flagged_count||0)}</strong></div><div><span>Answered</span><strong>${Number(s.answered||0)}/${Number(s.total||0)}</strong></div><div><span>Chat</span><strong>${Number(s.unread_messages||0)}</strong></div></div>
      <div class="monitor-last-event"><span>Latest event</span><strong>${esc((s.last_event||'No event yet').replaceAll('_',' '))}</strong>${s.last_event_detail?`<small>${esc(s.last_event_detail)}</small>`:''}</div>
      <div class="monitor-card-actions"><a class="primary button-link" href="/admin/session/${Number(s.id)}">Review Student</a></div>
    </article>`).join('');
  }
  async function refresh(){
    try{const r=await fetch(page.dataset.monitorEndpoint,{headers:{'Accept':'application/json'},cache:'no-store'});const data=await r.json();if(data.ok){render(data.students||[]);updated.textContent='Updated just now';}}
    catch(e){updated.textContent='Refresh failed';}
  }
  filter.addEventListener('change',refresh); document.getElementById('monitorRefresh').addEventListener('click',refresh);
  setInterval(refresh,10000);
})();
