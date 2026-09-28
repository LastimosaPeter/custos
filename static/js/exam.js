(() => {
  'use strict';
  const app = document.getElementById('examApp');
  if (!app) return;

  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const panels = [...document.querySelectorAll('.question-panel')];
  const navButtons = [...document.querySelectorAll('.qnav')];
  const position = document.getElementById('questionPosition');
  const saveStatus = document.getElementById('saveStatus');
  const currentPartIndicator = document.getElementById('currentPartIndicator');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const submitBtn = document.getElementById('submitBtn');
  const submitOverlay = document.getElementById('submitOverlay');
  const cancelSubmit = document.getElementById('cancelSubmit');
  const submitForm = document.getElementById('submitForm');
  const secureOverlay = document.getElementById('secureOverlay');
  const enterFullscreen = document.getElementById('enterFullscreen');
  const fullscreenError = document.getElementById('fullscreenError');
  const inactiveOverlay = document.getElementById('inactiveOverlay');
  const stillHereBtn = document.getElementById('stillHereBtn');
  const timerEl = document.getElementById('timer');
  const answeredStatus = document.getElementById('answeredStatus');
  const unansweredStatus = document.getElementById('unansweredStatus');
  const questionNav = document.getElementById('questionNavigator');
  const questionNavToggle = document.getElementById('questionNavToggle');
  const questionNavClose = document.getElementById('questionNavClose');
  const questionNavBackdrop = document.getElementById('questionNavBackdrop');
  const secureModeDescription = document.getElementById('secureModeDescription');
  const reviewFlagBtn = document.getElementById('reviewFlagBtn');
  const flaggedStatus = document.getElementById('flaggedStatus');

  const securityOverlay = document.getElementById('securityLockOverlay');
  const securityTitle = document.getElementById('securityLockTitle');
  const securityCountdown = document.getElementById('securityLockCountdown');
  const securityMessage = document.getElementById('securityLockMessage');
  const violationCountEl = document.getElementById('violationCount');
  const resumeSecureBtn = document.getElementById('resumeSecureBtn');
  const securityChatBtn = document.getElementById('securityChatBtn');

  const chatPanel = document.getElementById('chatPanel');
  const chatToggle = document.getElementById('chatToggle');
  const chatClose = document.getElementById('chatClose');
  const chatMessages = document.getElementById('chatMessages');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const chatStatus = document.getElementById('chatStatus');
  const chatUnreadBadge = document.getElementById('chatUnreadBadge');

  const untimed = app.dataset.untimed === '1';
  const isCustomAssessment = app.dataset.custom === '1';
  const isInstalledAppMode = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.matchMedia('(display-mode: fullscreen)').matches ||
    window.navigator.standalone === true;
  const secureDisplayActive = () => isInstalledAppMode() || Boolean(document.fullscreenElement);
  let current = Math.max(0, Math.min(Number(app.dataset.resumeIndex || 0), Math.max(panels.length - 1, 0)));
  let remaining = untimed ? null : Number(app.dataset.remaining || 0);
  let lastActivity = Date.now();
  let inactivityPrompted = false;
  let noResponseLogged = false;
  let secureModeEntered = false;
  let intentionalNavigation = false;
  let violationRequestInFlight = false;
  let temporaryLockEndsAt = 0;
  let lastInstructorMessageId = 0;
  let chatOpen = false;
  let securityState = {
    violationCount: Number(app.dataset.violationCount || 0),
    permanent: app.dataset.securityLocked === '1',
    pending: app.dataset.pendingBlackout === '1',
    tempRemaining: Number(app.dataset.tempLockRemaining || 0)
  };

  async function postJSON(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(payload),
      credentials: 'same-origin',
      keepalive: true
    });
  }

  function logEvent(type, detail = '') {
    postJSON('/api/proctor-event', {type, detail}).catch(() => {});
  }

  function persistQuestionPosition(index) {
    postJSON('/api/question-position', {index}).catch(() => {});
  }

  function flaggedCount() {
    return panels.filter(p => p.dataset.reviewFlagged === '1').length;
  }

  function updateReviewFlagUI() {
    if (!reviewFlagBtn || !panels[current]) return;
    const flagged = panels[current].dataset.reviewFlagged === '1';
    reviewFlagBtn.classList.toggle('active', flagged);
    reviewFlagBtn.setAttribute('aria-pressed', flagged ? 'true' : 'false');
    reviewFlagBtn.textContent = flagged ? 'Flagged for Review' : 'Flag for Review';
  }

  function showQuestion(index, persist = true) {
    current = Math.max(0, Math.min(index, panels.length - 1));
    panels.forEach((p, i) => p.classList.toggle('hidden', i !== current));
    navButtons.forEach((b, i) => b.classList.toggle('current', i === current));
    position.textContent = `Question ${current + 1} of ${panels.length}`;
    if (currentPartIndicator) {
      if (isCustomAssessment) {
        currentPartIndicator.textContent = 'Questions';
      } else {
        const part = panels[current].dataset.part;
        currentPartIndicator.textContent = part === '1'
          ? 'Part I · Code Tracing / Inspection'
          : (part === '2' ? 'Part II · Programming Logic / Code Selection' : 'Part III · Bonus Points');
      }
    }
    prevBtn.disabled = current === 0;
    nextBtn.textContent = current === panels.length - 1 ? 'Review' : 'Next';
    panels[current].scrollTop = 0;
    updateReviewFlagUI();
    if (persist) persistQuestionPosition(current);
    if (isInstalledAppMode() && window.matchMedia('(max-width: 1024px)').matches) setQuestionNavOpen(false);
  }

  function setQuestionNavOpen(open) {
    if (!questionNav) return;
    questionNav.classList.toggle('mobile-open', open);
    questionNavBackdrop?.classList.toggle('active', open);
    questionNavToggle?.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  questionNavToggle?.addEventListener('click', () => setQuestionNavOpen(!questionNav.classList.contains('mobile-open')));
  questionNavClose?.addEventListener('click', () => setQuestionNavOpen(false));
  questionNavBackdrop?.addEventListener('click', () => setQuestionNavOpen(false));

  navButtons.forEach(btn => btn.addEventListener('click', () => showQuestion(Number(btn.dataset.index))));
  prevBtn.addEventListener('click', () => showQuestion(current - 1));
  nextBtn.addEventListener('click', () => {
    if (current < panels.length - 1) {
      showQuestion(current + 1);
      return;
    }
    const flaggedIndex = panels.findIndex(p => p.dataset.reviewFlagged === '1');
    if (flaggedIndex >= 0) showQuestion(flaggedIndex);
    else {
      const unansweredIndex = panels.findIndex(p => !p.querySelector('input:checked') && !(p.querySelector('.bonus-answer-input')?.value.trim()));
      if (unansweredIndex >= 0) showQuestion(unansweredIndex);
      else setQuestionNavOpen(true);
    }
  });

  function answeredCount() {
    return panels.filter(p => p.querySelector('input:checked') || (p.querySelector('.bonus-answer-input')?.value.trim())).length;
  }

  function updateFooterStatus() {
    const answered = answeredCount();
    if (answeredStatus) answeredStatus.textContent = `${answered}/${panels.length}`;
    if (unansweredStatus) unansweredStatus.textContent = String(panels.length - answered);
    if (flaggedStatus) flaggedStatus.textContent = String(flaggedCount());
  }

  reviewFlagBtn?.addEventListener('click', async () => {
    const panel = panels[current];
    if (!panel?.dataset.questionId) return;
    const nextFlagged = panel.dataset.reviewFlagged !== '1';
    reviewFlagBtn.disabled = true;
    try {
      const res = await postJSON('/api/question-review', {question_id: Number(panel.dataset.questionId), flagged: nextFlagged});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error('review flag save failed');
      panel.dataset.reviewFlagged = data.flagged ? '1' : '0';
      navButtons[current]?.classList.toggle('review-flagged', Boolean(data.flagged));
      updateReviewFlagUI();
      updateFooterStatus();
      saveStatus.textContent = data.flagged ? 'Flagged for review' : 'Review flag removed';
      saveStatus.className = 'save-status saved';
    } catch (_) {
      saveStatus.textContent = 'Could not save review flag';
      saveStatus.className = 'save-status error';
    } finally {
      reviewFlagBtn.disabled = false;
    }
  });

  document.querySelectorAll('.answer-choice input').forEach(input => {
    input.addEventListener('change', async () => {
      const panel = input.closest('.question-panel');
      const qid = panel.dataset.questionId;
      const idx = Number(panel.dataset.index);
      navButtons[idx].classList.add('answered');
      updateFooterStatus();
      saveStatus.textContent = 'Saving…';
      saveStatus.className = 'save-status saving';
      try {
        const res = await postJSON('/api/answer', {question_id: qid, answer: input.value});
        const data = await res.json().catch(() => ({}));
        if (res.status === 423 && data.locked) {
          applySecurityState(data);
          throw new Error('security locked');
        }
        if (!res.ok) throw new Error('save failed');
        saveStatus.textContent = 'Saved';
        saveStatus.className = 'save-status saved';
      } catch (_) {
        saveStatus.textContent = securityState.permanent || securityState.pending || securityState.tempRemaining > 0
          ? 'Security lock — answer not saved'
          : 'Save failed — retry selection';
        saveStatus.className = 'save-status error';
      }
    });
  });

  const bonusTimers = new Map();
  async function saveBonusInput(input) {
    const panel = input.closest('.question-panel');
    const qid = panel.dataset.bonusQuestionId;
    const idx = Number(panel.dataset.index);
    const value = input.value;
    navButtons[idx].classList.toggle('answered', Boolean(value.trim()));
    updateFooterStatus();
    saveStatus.textContent = 'Saving…';
    saveStatus.className = 'save-status saving';
    try {
      const res = await postJSON('/api/bonus-answer', {bonus_question_id: qid, answer: value});
      const data = await res.json().catch(() => ({}));
      if (res.status === 423 && data.locked) {
        applySecurityState(data);
        throw new Error('security locked');
      }
      if (!res.ok) throw new Error('save failed');
      saveStatus.textContent = 'Saved';
      saveStatus.className = 'save-status saved';
    } catch (_) {
      saveStatus.textContent = securityState.permanent || securityState.pending || securityState.tempRemaining > 0
        ? 'Security lock — answer not saved'
        : 'Save failed — retry';
      saveStatus.className = 'save-status error';
    }
  }

  document.querySelectorAll('.bonus-answer-input').forEach(input => {
    input.addEventListener('input', () => {
      const panel = input.closest('.question-panel');
      const idx = Number(panel.dataset.index);
      navButtons[idx].classList.toggle('answered', Boolean(input.value.trim()));
      updateFooterStatus();
      clearTimeout(bonusTimers.get(input));
      bonusTimers.set(input, setTimeout(() => saveBonusInput(input), 500));
    });
    input.addEventListener('blur', () => {
      clearTimeout(bonusTimers.get(input));
      saveBonusInput(input);
    });
  });

  submitBtn.addEventListener('click', () => {
    const answered = answeredCount();
    const flagged = flaggedCount();
    document.getElementById('submitSummary').textContent = `${answered} of ${panels.length} questions are answered.${flagged ? ` ${flagged} item${flagged === 1 ? '' : 's'} still flagged for review.` : ''} Unanswered questions will be marked incorrect. Submission cannot be undone.`;
    submitOverlay.classList.add('active');
  });
  cancelSubmit.addEventListener('click', () => submitOverlay.classList.remove('active'));
  submitForm.addEventListener('submit', () => { intentionalNavigation = true; });
  document.querySelectorAll('.test-return-form, .security-admin-return').forEach(form => {
    form.addEventListener('submit', () => { intentionalNavigation = true; });
  });

  async function requestSecureMode() {
    fullscreenError.classList.add('hidden');
    if (securityState.permanent || securityState.pending || securityState.tempRemaining > 0) return;

    if (isInstalledAppMode()) {
      secureModeEntered = true;
      secureOverlay.classList.remove('active');
      securityOverlay.classList.remove('active');
      document.documentElement.classList.add('pwa-standalone');
      logEvent('standalone_secure_mode_enter', 'Installed Custos app secure mode entered');
      registerActivity();
      return;
    }

    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      secureModeEntered = true;
      secureOverlay.classList.remove('active');
      securityOverlay.classList.remove('active');
      logEvent('fullscreen_enter', 'Fullscreen secure mode entered');
      registerActivity();
    } catch (e) {
      fullscreenError.classList.remove('hidden');
      if (secureModeDescription && /iPad|iPhone|iPod/.test(navigator.userAgent)) {
        secureModeDescription.textContent = 'On iPhone or iPad, install Custos from Safari using Share → Add to Home Screen, launch it from the Home Screen, then return to this exam. Installed app mode is accepted as secure display mode.';
      }
      logEvent('fullscreen_denied', String(e));
    }
  }
  enterFullscreen.addEventListener('click', requestSecureMode);
  resumeSecureBtn.addEventListener('click', requestSecureMode);

  function renderSecurityOverlay() {
    if (violationCountEl) violationCountEl.textContent = String(securityState.violationCount);
    if (securityState.permanent) {
      securityOverlay.classList.add('active', 'permanent');
      securityTitle.textContent = 'Attempt Locked';
      securityCountdown.textContent = 'INSTRUCTOR REQUIRED';
      securityMessage.textContent = 'Three or more major security violations were recorded. Only the instructor can unlock this attempt. The exam timer continues while locked.';
      resumeSecureBtn.classList.add('hidden');
      return;
    }

    securityOverlay.classList.remove('permanent');
    if (securityState.pending) {
      securityOverlay.classList.add('active');
      securityTitle.textContent = 'Security Event Detected';
      securityCountdown.textContent = '…';
      securityMessage.textContent = 'A focus/fullscreen violation was recorded. The 15-second blackout penalty will begin when this exam has focus.';
      resumeSecureBtn.classList.add('hidden');
      return;
    }
    if (securityState.tempRemaining > 0) {
      temporaryLockEndsAt = Date.now() + (securityState.tempRemaining * 1000);
      securityOverlay.classList.add('active');
      securityTitle.textContent = 'Security Lock';
      securityMessage.textContent = 'The exam is temporarily unavailable because a focus/fullscreen violation was detected. The timer continues to run.';
      resumeSecureBtn.classList.add('hidden');
      return;
    }

    if (!secureDisplayActive() && secureModeEntered) {
      securityOverlay.classList.add('active');
      securityTitle.textContent = 'Security Lock Complete';
      securityCountdown.textContent = 'READY';
      securityMessage.textContent = 'The 15-second lock has ended. Return to fullscreen to continue the exam.';
      resumeSecureBtn.classList.remove('hidden');
    } else {
      securityOverlay.classList.remove('active');
      resumeSecureBtn.classList.add('hidden');
    }
  }

  function applySecurityState(data) {
    securityState.violationCount = Number(data.violation_count ?? data.violationCount ?? securityState.violationCount);
    securityState.permanent = Boolean(data.permanent);
    securityState.pending = Boolean(data.pending);
    securityState.tempRemaining = Number(data.temp_remaining ?? data.tempRemaining ?? 0);
    renderSecurityOverlay();
  }

  async function triggerViolation(source) {
    if (!secureModeEntered || intentionalNavigation || securityState.permanent || securityState.pending || securityState.tempRemaining > 0 || violationRequestInFlight) return;
    violationRequestInFlight = true;
    securityOverlay.classList.add('active');
    securityTitle.textContent = 'Security Event Detected';
    securityCountdown.textContent = '…';
    securityMessage.textContent = 'Custos is recording and verifying this focus/fullscreen event.';
    resumeSecureBtn.classList.add('hidden');
    try {
      const res = await postJSON('/api/security-violation', {source});
      const data = await res.json().catch(() => ({}));
      if (data.ok) {
        applySecurityState(data);
        if (securityState.pending && !document.hidden && document.hasFocus()) await startPendingBlackout();
      } else await refreshSecurityStatus();
    } catch (_) {
      await refreshSecurityStatus();
    } finally {
      violationRequestInFlight = false;
    }
  }

  async function startPendingBlackout() {
    if (!securityState.pending || securityState.permanent) return;
    try {
      const res = await postJSON('/api/security-start-lock', {});
      const data = await res.json().catch(() => ({}));
      if (data.ok) applySecurityState(data);
    } catch (_) {}
  }

  async function refreshSecurityStatus() {
    try {
      const res = await fetch('/api/security-status', {credentials: 'same-origin', cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      if (data.ok) {
        applySecurityState(data);
        if (securityState.pending && !document.hidden && document.hasFocus()) await startPendingBlackout();
      }
    } catch (_) {}
  }

  document.addEventListener('fullscreenchange', () => {
    if (!secureModeEntered || intentionalNavigation || isInstalledAppMode()) return;
    if (!document.fullscreenElement) triggerViolation('fullscreen_exit');
    else if (!securityState.permanent && securityState.tempRemaining <= 0) {
      secureOverlay.classList.remove('active');
      securityOverlay.classList.remove('active');
    }
  });

  document.addEventListener('visibilitychange', async () => {
    if (document.hidden) {
      if (secureModeEntered && !intentionalNavigation) triggerViolation('tab_hidden');
    } else {
      logEvent('tab_visible', 'Exam page became visible');
      await refreshSecurityStatus();
      if (securityState.pending) await startPendingBlackout();
    }
  });

  window.addEventListener('blur', () => {
    if (secureModeEntered && !intentionalNavigation) triggerViolation('window_blur');
  });
  window.addEventListener('focus', async () => {
    if (secureModeEntered) {
      logEvent('window_focus', 'Exam window regained focus');
      await refreshSecurityStatus();
      if (securityState.pending) await startPendingBlackout();
    }
  });

  document.addEventListener('contextmenu', e => {
    e.preventDefault();
    logEvent('contextmenu', 'Right-click/context menu attempt blocked');
  });

  document.addEventListener('keydown', e => {
    const key = e.key.toLowerCase();
    const blocked =
      e.key === 'F12' ||
      (e.ctrlKey && e.shiftKey && ['i', 'j', 'c'].includes(key)) ||
      (e.ctrlKey && ['u', 's', 'p'].includes(key)) ||
      (e.metaKey && e.altKey && ['i', 'j', 'c'].includes(key));
    if (blocked) {
      e.preventDefault();
      logEvent('blocked_shortcut', `Blocked browser shortcut: ${e.key}`);
    }
    registerActivity();
  }, true);

  ['mousemove', 'mousedown', 'touchstart', 'scroll'].forEach(name => {
    window.addEventListener(name, registerActivity, {passive: true});
  });

  function registerActivity() {
    lastActivity = Date.now();
    if (!inactiveOverlay.classList.contains('active')) {
      inactivityPrompted = false;
      noResponseLogged = false;
    }
  }

  stillHereBtn.addEventListener('click', () => {
    inactiveOverlay.classList.remove('active');
    logEvent('inactivity_acknowledged', 'Student responded to inactivity prompt');
    lastActivity = Date.now();
    inactivityPrompted = false;
    noResponseLogged = false;
  });

  setInterval(() => {
    if (!secureModeEntered || securityState.permanent || securityState.pending || securityState.tempRemaining > 0) return;
    const idle = Date.now() - lastActivity;
    if (idle >= 60000 && !inactivityPrompted) {
      inactivityPrompted = true;
      inactiveOverlay.classList.add('active');
      logEvent('inactivity', 'No detected activity for 60 seconds');
    }
    if (idle >= 90000 && inactivityPrompted && !noResponseLogged) {
      noResponseLogged = true;
      logEvent('inactivity_no_response', 'No response 30 seconds after inactivity prompt');
    }
  }, 1000);

  function renderTimer() {
    if (untimed) {
      if (timerEl) timerEl.textContent = 'Untimed';
      return;
    }
    const safe = Math.max(0, remaining);
    const h = Math.floor(safe / 3600);
    const m = Math.floor((safe % 3600) / 60);
    const s = safe % 60;
    timerEl.textContent = [h, m, s].map(v => String(v).padStart(2, '0')).join(':');
    if (safe <= 300) timerEl.classList.add('timer-warning');
    if (safe === 0) {
      logEvent('timer_expired', 'Client timer reached zero');
      intentionalNavigation = true;
      window.location.assign('/exam');
      return;
    }
    remaining -= 1;
  }
  renderTimer();
  if (!untimed) setInterval(renderTimer, 1000);

  window.addEventListener('beforeunload', () => {
    if (!intentionalNavigation && (untimed || remaining > 0)) logEvent('beforeunload', 'Page navigation/reload initiated');
  });

  ['copy', 'cut', 'paste'].forEach(evt => document.addEventListener(evt, e => {
    e.preventDefault();
    logEvent('blocked_shortcut', `${evt} attempt blocked`);
  }));

  // --- Student ↔ instructor chat ---
  function setChatOpen(open) {
    chatOpen = open;
    chatPanel.classList.toggle('active', open);
    chatPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
    if (open) {
      chatUnreadBadge.classList.add('hidden');
      chatUnreadBadge.textContent = '0';
      fetchChatMessages();
      setTimeout(() => chatInput.focus(), 60);
    }
  }
  chatToggle.addEventListener('click', () => setChatOpen(true));
  chatClose.addEventListener('click', () => setChatOpen(false));
  securityChatBtn.addEventListener('click', () => setChatOpen(true));

  function renderChat(messages) {
    const previousInstructorMax = lastInstructorMessageId;
    chatMessages.innerHTML = '';
    if (!messages.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-empty';
      empty.textContent = 'No messages yet. Use this chat for exam clarifications.';
      chatMessages.appendChild(empty);
      return;
    }
    let newInstructorCount = 0;
    for (const m of messages) {
      if (m.sender === 'instructor') {
        if (m.id > previousInstructorMax && !chatOpen) newInstructorCount += 1;
        lastInstructorMessageId = Math.max(lastInstructorMessageId, m.id);
      }
      const item = document.createElement('div');
      item.className = `chat-message ${m.sender}`;
      const meta = document.createElement('div');
      meta.className = 'chat-message-meta';
      meta.textContent = `${m.sender === 'student' ? 'You' : 'Instructor'} · ${m.created_at}`;
      const body = document.createElement('div');
      body.textContent = m.message;
      item.append(meta, body);
      chatMessages.appendChild(item);
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
    if (newInstructorCount && !chatOpen) {
      chatUnreadBadge.textContent = String(newInstructorCount);
      chatUnreadBadge.classList.remove('hidden');
    }
  }

  async function fetchChatMessages() {
    try {
      const res = await fetch(`/api/chat/messages?mark_read=${chatOpen ? '1' : '0'}`, {credentials: 'same-origin', cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      if (data.ok) renderChat(data.messages || []);
    } catch (_) {}
  }

  chatForm.addEventListener('submit', async e => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    chatStatus.textContent = 'Sending…';
    try {
      const res = await postJSON('/api/chat/send', {message});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error('send failed');
      chatInput.value = '';
      chatStatus.textContent = 'Sent';
      await fetchChatMessages();
      setTimeout(() => { chatStatus.textContent = ''; }, 1500);
    } catch (_) {
      chatStatus.textContent = 'Could not send. Try again.';
    }
  });

  // Update the temporary blackout countdown without pausing the exam timer.
  setInterval(() => {
    if (securityState.permanent) return;
    if (securityState.tempRemaining > 0) {
      const seconds = Math.max(0, Math.ceil((temporaryLockEndsAt - Date.now()) / 1000));
      securityCountdown.textContent = String(seconds).padStart(2, '0');
      if (seconds <= 0) refreshSecurityStatus();
    }
  }, 250);

  setInterval(() => {
    if (securityState.permanent || securityState.pending || securityState.tempRemaining > 0) refreshSecurityStatus();
  }, 3000);
  // Chat is useful during an exam, but polling every 3 seconds from every
  // student creates unnecessary database traffic. Poll quickly only while the
  // chat is open, back off while it is closed, and pause network polling when
  // the page is hidden.
  let chatPollTimer = null;
  function scheduleChatPoll(delay) {
    if (chatPollTimer) clearTimeout(chatPollTimer);
    const nextDelay = delay ?? (chatOpen ? 5000 : 12000);
    chatPollTimer = setTimeout(async () => {
      if (!document.hidden) await fetchChatMessages();
      scheduleChatPoll();
    }, nextDelay);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) fetchChatMessages();
    scheduleChatPoll(document.hidden ? 20000 : 1000);
  });
  scheduleChatPoll();

  if (isInstalledAppMode()) {
    document.documentElement.classList.add('pwa-standalone');
    if (enterFullscreen) enterFullscreen.textContent = 'Begin Exam in App Mode';
    if (secureModeDescription) secureModeDescription.textContent = 'Custos detected installed app mode. Keep Custos in the foreground throughout the exam. Switching to another app, opening another browser, or leaving the exam can trigger a security violation.';
  }

  updateFooterStatus();
  showQuestion(current, false);
  renderSecurityOverlay();
  fetchChatMessages();
})();
