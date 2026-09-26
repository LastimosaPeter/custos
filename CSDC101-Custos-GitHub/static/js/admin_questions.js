(function(){
  const dialog=document.getElementById('questionEditDialog');
  const form=document.getElementById('questionEditForm');
  if(!dialog||!form) return;
  const fields={
    batch_slot:document.getElementById('editBatchSlot'), part:document.getElementById('editPart'),
    topic:document.getElementById('editTopic'), prompt:document.getElementById('editPrompt'), code:document.getElementById('editCode'),
    option_a:document.getElementById('editOptionA'), option_b:document.getElementById('editOptionB'), option_c:document.getElementById('editOptionC'), option_d:document.getElementById('editOptionD'),
    correct_option:document.getElementById('editCorrect'), explanation:document.getElementById('editExplanation')
  };
  document.querySelectorAll('.js-edit-question').forEach(btn=>btn.addEventListener('click',()=>{
    let q; try{q=JSON.parse(btn.dataset.question);}catch(e){return;}
    Object.entries(fields).forEach(([key,el])=>{ if(el) el.value=q[key] ?? ''; });
    document.getElementById('editQuestionTitle').textContent=`Question ${q.id}`;
    form.action=btn.dataset.editUrl || `/admin/questions/${q.id}/edit`;
    if(typeof dialog.showModal==='function') dialog.showModal(); else dialog.setAttribute('open','');
  }));
  document.querySelectorAll('[data-close-edit]').forEach(btn=>btn.addEventListener('click',()=>dialog.close()));
  dialog.addEventListener('click',e=>{ if(e.target===dialog) dialog.close(); });
})();
