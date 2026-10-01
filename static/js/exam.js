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

  const labToolkitPanel = document.getElementById('labToolkitPanel');
  const labToolkitToggle = document.getElementById('labToolkitToggle');
  const labToolkitClose = document.getElementById('labToolkitClose');
  const labToolkitBackdrop = document.getElementById('labToolkitBackdrop');
  const labToolkitTabs = [...document.querySelectorAll('[data-toolkit-case]')];
  const labToolkitSections = [...document.querySelectorAll('[data-toolkit-section]')];
  const labLayoutButtons = [...document.querySelectorAll('[data-lab-layout-mode]')];
  const labQuestionPeek = document.getElementById('labQuestionPeek');
  const labQuestionBackdrop = document.getElementById('labQuestionBackdrop');
  const questionFocusBtn = document.getElementById('questionFocusBtn');
  const imageViewer = document.getElementById('examImageViewer');
  const imageViewerImage = document.getElementById('examImageViewerImage');
  const imageViewerTitle = document.getElementById('examImageViewerTitle');
  const imageViewerStage = document.getElementById('examImageViewerStage');
  const imageViewerClose = document.getElementById('examImageViewerClose');
  const imageZoomIn = document.getElementById('examImageZoomIn');
  const imageZoomOut = document.getElementById('examImageZoomOut');
  const imageZoomReset = document.getElementById('examImageZoomReset');
  const labFontButtons = [...document.querySelectorAll('[data-lab-font-delta]')];
  const labFontReset = document.querySelector('[data-lab-font-reset]');
  const labFontReadout = document.getElementById('labFontReadout');

  const untimed = app.dataset.untimed === '1';
  const isCustomAssessment = app.dataset.custom === '1';
  const securityMode = app.dataset.securityMode || 'strict';
  const strictSecurity = securityMode === 'strict';
  // Installed-app (PWA) mode is accepted as secure display only where the page
  // cannot use real element fullscreen: iPhone/iPad, or any browser without the
  // Fullscreen API. Elsewhere '(display-mode: fullscreen)' also matches when a
  // student presses F11 (browser fullscreen), which the page cannot detect
  // leaving - trusting it there let F11 exit secure mode with no violation.
  const isAppleTouchDevice = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const fullscreenApiUsable = Boolean(document.fullscreenEnabled && document.documentElement.requestFullscreen);
  const isInstalledAppMode = () =>
    (isAppleTouchDevice || !fullscreenApiUsable) && (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.matchMedia('(display-mode: fullscreen)').matches ||
      window.navigator.standalone === true);
  const secureDisplayActive = () => isInstalledAppMode() || Boolean(document.fullscreenElement);
  let current = Math.max(0, Math.min(Number(app.dataset.resumeIndex || 0), Math.max(panels.length - 1, 0)));
  let remaining = untimed ? null : Number(app.dataset.remaining || 0);
  let lastActivity = Date.now();
  let inactivityPrompted = false;
  let noResponseLogged = false;
  let secureModeEntered = !strictSecurity;
  let intentionalNavigation = false;
  let violationRequestInFlight = false;
  let temporaryLockEndsAt = 0;
  let lastInstructorMessageId = 0;
  let chatOpen = false;
  let securityState = {
    violationCount: Number(app.dataset.violationCount || 0),
    permanent: app.dataset.securityLocked === '1',
    pending: app.dataset.pendingBlackout === '1',
    resumeRequired: app.dataset.securityResumeRequired === '1',
    tempRemaining: Number(app.dataset.tempLockRemaining || 0)
  };
  const behaviorCounters = {
    questionChanges: 0,
    answerChanges: 0,
    selectionAttempts: 0,
    dragAttempts: 0,
    printAttempts: 0,
    activeQuestionSeconds: 0
  };
  let questionEnteredAt = Date.now();

  async function postJSON(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(payload),
      credentials: 'same-origin',
      keepalive: true
    });
  }

  // Ordinary telemetry is buffered so 30–100 simultaneous examinees do not
  // create a database write for every harmless interaction. Security violations
  // still use the dedicated immediate endpoint below.
  const proctorEventQueue = [];
  let proctorFlushTimer = null;
  let proctorFlushInFlight = false;
  const PROCTOR_BATCH_SIZE = 25;
  const PROCTOR_QUEUE_LIMIT = 50;

  async function flushProctorEvents() {
    if (!strictSecurity || proctorFlushInFlight || !proctorEventQueue.length) return;
    if (proctorFlushTimer) clearTimeout(proctorFlushTimer);
    proctorFlushTimer = null;
    const batch = proctorEventQueue.splice(0, PROCTOR_BATCH_SIZE);
    proctorFlushInFlight = true;
    try {
      const response = await postJSON('/api/proctor-events', {events: batch});
      if (!response.ok) throw new Error('telemetry save failed');
    } catch (_) {
      proctorEventQueue.unshift(...batch);
      if (proctorEventQueue.length > PROCTOR_QUEUE_LIMIT) proctorEventQueue.splice(0, proctorEventQueue.length - PROCTOR_QUEUE_LIMIT);
    } finally {
      proctorFlushInFlight = false;
      if (proctorEventQueue.length) proctorFlushTimer = setTimeout(flushProctorEvents, 15000);
    }
  }

  function logEvent(type, detail = '') {
    if (!strictSecurity) return;
    proctorEventQueue.push({type, detail: String(detail || '').slice(0, 500)});
    if (proctorEventQueue.length > PROCTOR_QUEUE_LIMIT) proctorEventQueue.shift();
    if (proctorEventQueue.length >= 8) {
      flushProctorEvents();
    } else if (!proctorFlushTimer) {
      proctorFlushTimer = setTimeout(flushProctorEvents, 15000);
    }
  }

  let questionPositionTimer = null;
  let pendingQuestionPosition = null;
  function persistQuestionPosition(index, immediate = false) {
    pendingQuestionPosition = index;
    clearTimeout(questionPositionTimer);
    const save = () => {
      if (pendingQuestionPosition === null) return;
      const next = pendingQuestionPosition;
      pendingQuestionPosition = null;
      postJSON('/api/question-position', {index: next}).catch(() => {});
    };
    if (immediate) save();
    else questionPositionTimer = setTimeout(save, 800);
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

  function setLabToolkitSection(caseKey) {
    if (!labToolkitPanel || !labToolkitSections.length) return;
    const requested = caseKey || 'GUIDE';
    const exists = labToolkitSections.some(section => section.dataset.toolkitSection === requested);
    const activeKey = exists ? requested : 'GUIDE';
    labToolkitSections.forEach(section => section.classList.toggle('hidden', section.dataset.toolkitSection !== activeKey));
    labToolkitTabs.forEach(tab => {
      const active = tab.dataset.toolkitCase === activeKey;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const scroll = labToolkitPanel.querySelector('.lab-toolkit-scroll');
    if (scroll) scroll.scrollTop = 0;
    window.dispatchEvent(new CustomEvent('custos:workbench-layoutchange', {detail: {section: activeKey}}));
  }

  function syncLabToolkitToQuestion() {
    if (!labToolkitPanel || !panels[current]) return;
    setLabToolkitSection(panels[current].dataset.caseKey || 'GUIDE');
  }

  function currentLabLayout() {
    return app.dataset.labLayout || 'split';
  }

  function labToolkitUsesDrawer() {
    return window.matchMedia('(max-width: 900px)').matches || currentLabLayout() === 'question';
  }

  function setLabToolkitOpen(open) {
    if (!labToolkitPanel) return;
    if (!labToolkitUsesDrawer()) {
      labToolkitPanel.classList.remove('drawer-open');
      labToolkitPanel.setAttribute('aria-hidden', 'false');
      labToolkitBackdrop?.classList.remove('active');
      labToolkitToggle?.setAttribute('aria-expanded', 'false');
      return;
    }
    labToolkitPanel.classList.toggle('drawer-open', open);
    labToolkitPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
    labToolkitBackdrop?.classList.toggle('active', open);
    labToolkitToggle?.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function setLabQuestionDrawer(open) {
    if (!labQuestionPeek) return;
    const canDrawer = currentLabLayout() === 'workbench' && !window.matchMedia('(max-width: 900px)').matches;
    app.classList.toggle('lab-question-drawer-open', Boolean(open && canDrawer));
    labQuestionBackdrop?.classList.toggle('active', Boolean(open && canDrawer));
    labQuestionPeek.setAttribute('aria-expanded', open && canDrawer ? 'true' : 'false');
  }

  function setLabLayout(mode, persist = true) {
    if (!labToolkitPanel) return;
    const allowed = ['question', 'split', 'workbench'];
    const next = allowed.includes(mode) ? mode : 'split';
    app.dataset.labLayout = next;
    app.classList.toggle('lab-layout-question', next === 'question');
    app.classList.toggle('lab-layout-split', next === 'split');
    app.classList.toggle('lab-layout-workbench', next === 'workbench');
    labLayoutButtons.forEach(btn => {
      const active = btn.dataset.labLayoutMode === next;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    questionFocusBtn?.classList.toggle('active', next === 'question');
    labQuestionPeek?.classList.toggle('visible', next === 'workbench');
    setLabQuestionDrawer(false);
    setLabToolkitOpen(false);
    if (persist) {
      try { localStorage.setItem('custos-csec303-lab-layout', next); } catch (_) {}
    }
    window.dispatchEvent(new CustomEvent('custos:workbench-layoutchange', {detail: {layout: next}}));
  }

  labToolkitToggle?.addEventListener('click', () => setLabToolkitOpen(!labToolkitPanel?.classList.contains('drawer-open')));
  labToolkitClose?.addEventListener('click', () => setLabToolkitOpen(false));
  labToolkitBackdrop?.addEventListener('click', () => setLabToolkitOpen(false));
  labToolkitTabs.forEach(tab => tab.addEventListener('click', () => setLabToolkitSection(tab.dataset.toolkitCase)));
  labLayoutButtons.forEach(btn => btn.addEventListener('click', () => setLabLayout(btn.dataset.labLayoutMode)));
  questionFocusBtn?.addEventListener('click', () => setLabLayout(currentLabLayout() === 'question' ? 'split' : 'question'));
  labQuestionPeek?.addEventListener('click', () => setLabQuestionDrawer(!app.classList.contains('lab-question-drawer-open')));
  labQuestionBackdrop?.addEventListener('click', () => setLabQuestionDrawer(false));
  window.addEventListener('resize', () => {
    setLabToolkitOpen(false);
    setLabQuestionDrawer(false);
  });

  if (labToolkitPanel) {
    let savedLayout = 'split';
    try { savedLayout = localStorage.getItem('custos-csec303-lab-layout') || 'split'; } catch (_) {}
    setLabLayout(savedLayout, false);
  }

  const LAB_FONT_DEFAULT = 12;
  const LAB_FONT_MIN = 10;
  const LAB_FONT_MAX = 20;
  let labFontSize = LAB_FONT_DEFAULT;

  function setLabFontSize(value, persist = true) {
    if (!labToolkitPanel) return;
    const next = Math.max(LAB_FONT_MIN, Math.min(LAB_FONT_MAX, Number(value) || LAB_FONT_DEFAULT));
    labFontSize = next;
    app.style.setProperty('--lab-code-font-size', `${next}px`);
    if (labFontReadout) labFontReadout.textContent = `${next} px`;
    labFontButtons.forEach(btn => {
      const delta = Number(btn.dataset.labFontDelta || 0);
      btn.disabled = (delta < 0 && next <= LAB_FONT_MIN) || (delta > 0 && next >= LAB_FONT_MAX);
    });
    if (persist) {
      try { localStorage.setItem('custos-csec303-code-font-size', String(next)); } catch (_) {}
    }
  }

  labFontButtons.forEach(btn => btn.addEventListener('click', () => setLabFontSize(labFontSize + Number(btn.dataset.labFontDelta || 0))));
  labFontReset?.addEventListener('click', () => setLabFontSize(LAB_FONT_DEFAULT));
  if (labToolkitPanel) {
    let savedFont = LAB_FONT_DEFAULT;
    try { savedFont = Number(localStorage.getItem('custos-csec303-code-font-size') || LAB_FONT_DEFAULT); } catch (_) {}
    setLabFontSize(savedFont, false);
  }

  let imageViewerScale = 1;

  function applyImageViewerScale() {
    if (!imageViewerImage) return;
    imageViewerImage.style.transform = `scale(${imageViewerScale})`;
  }

  function openImageViewer(img) {
    if (!imageViewer || !imageViewerImage || !img) return;
    imageViewerScale = 1;
    imageViewerImage.src = img.currentSrc || img.src;
    imageViewerImage.alt = img.alt || 'Expanded evidence image';
    if (imageViewerTitle) imageViewerTitle.textContent = img.alt || 'Image Preview';
    applyImageViewerScale();
    imageViewer.classList.add('active');
    imageViewer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('exam-image-viewer-open');
  }

  function closeImageViewer() {
    if (!imageViewer) return;
    imageViewer.classList.remove('active');
    imageViewer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('exam-image-viewer-open');
    if (imageViewerImage) imageViewerImage.removeAttribute('src');
  }

  function adjustImageZoom(delta) {
    imageViewerScale = Math.max(0.5, Math.min(5, Number((imageViewerScale + delta).toFixed(2))));
    applyImageViewerScale();
  }

  if (imageViewer) {
    const zoomableSelector = '.lab-case-media img, .lab-notebook-section-heading img, .lab-python-plots img, .lab-notebook-markdown img';
    document.querySelectorAll(zoomableSelector).forEach(img => {
      img.classList.add('exam-zoomable-image');
      img.setAttribute('tabindex', '0');
      img.setAttribute('role', 'button');
      img.setAttribute('title', 'Open image viewer');
    });
    document.addEventListener('click', event => {
      const img = event.target.closest?.(zoomableSelector);
      if (img) openImageViewer(img);
    });
    document.addEventListener('keydown', event => {
      const target = event.target;
      if ((event.key === 'Enter' || event.key === ' ') && target?.matches?.(zoomableSelector)) {
        event.preventDefault();
        openImageViewer(target);
        return;
      }
      if (event.key === 'Escape' && imageViewer.classList.contains('active')) closeImageViewer();
    });
    imageViewerClose?.addEventListener('click', closeImageViewer);
    imageZoomIn?.addEventListener('click', () => adjustImageZoom(0.25));
    imageZoomOut?.addEventListener('click', () => adjustImageZoom(-0.25));
    imageZoomReset?.addEventListener('click', () => { imageViewerScale = 1; applyImageViewerScale(); });
    imageViewerStage?.addEventListener('wheel', event => {
      event.preventDefault();
      adjustImageZoom(event.deltaY < 0 ? 0.2 : -0.2);
    }, {passive:false});
    imageViewerStage?.addEventListener('click', event => {
      if (event.target === imageViewerStage) closeImageViewer();
    });
  }

  function showQuestion(index, persist = true) {
    const nextIndex = Math.max(0, Math.min(index, panels.length - 1));
    if (nextIndex !== current) {
      behaviorCounters.questionChanges += 1;
      behaviorCounters.activeQuestionSeconds += Math.max(0, Math.round((Date.now() - questionEnteredAt) / 1000));
      questionEnteredAt = Date.now();
    }
    current = nextIndex;
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
    syncLabToolkitToQuestion();
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
      if (res.status === 423 && data.locked) {
        applySecurityState(data);
        throw new Error('security locked');
      }
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
      behaviorCounters.answerChanges += 1;
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
        saveStatus.textContent = securityState.permanent || securityState.pending || securityState.resumeRequired || securityState.tempRemaining > 0
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
      saveStatus.textContent = securityState.permanent || securityState.pending || securityState.resumeRequired || securityState.tempRemaining > 0
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
      bonusTimers.set(input, setTimeout(() => saveBonusInput(input), 900));
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

  async function confirmSecurityResume() {
    if (!securityState.resumeRequired) return true;
    try {
      const res = await postJSON('/api/security-resume', {secure_active: secureDisplayActive()});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        if (data.locked) applySecurityState(data);
        return false;
      }
      applySecurityState(data);
      logEvent('security_resume_client_confirmed', 'Secure display mode restored after instructor unlock');
      return !securityState.resumeRequired;
    } catch (_) {
      return false;
    }
  }

  async function requestSecureMode() {
    if (!strictSecurity) {
      secureOverlay?.classList.remove('active');
      return;
    }
    fullscreenError.classList.add('hidden');
    if (securityState.permanent || securityState.pending || securityState.tempRemaining > 0) return;

    if (isInstalledAppMode()) {
      secureModeEntered = true;
      document.documentElement.classList.add('pwa-standalone');
      logEvent('standalone_secure_mode_enter', 'Installed Custos app secure mode entered');
      registerActivity();
      if (securityState.resumeRequired) {
        const resumed = await confirmSecurityResume();
        if (!resumed) {
          securityOverlay.classList.add('active');
          fullscreenError.classList.remove('hidden');
          return;
        }
      }
      secureOverlay.classList.remove('active');
      renderSecurityOverlay();
      return;
    }

    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      secureModeEntered = true;
      logEvent('fullscreen_enter', 'Fullscreen secure mode entered');
      registerActivity();
      if (securityState.resumeRequired) {
        const resumed = await confirmSecurityResume();
        if (!resumed) {
          securityOverlay.classList.add('active');
          fullscreenError.classList.remove('hidden');
          return;
        }
      }
      secureOverlay.classList.remove('active');
      renderSecurityOverlay();
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
    if (!strictSecurity) {
      secureOverlay?.classList.remove('active');
      securityOverlay?.classList.remove('active');
      return;
    }
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
    if (securityState.resumeRequired) {
      securityOverlay.classList.add('active');
      securityTitle.textContent = 'Secure Mode Required';
      securityCountdown.textContent = 'READY';
      securityMessage.textContent = 'Your instructor granted another chance. Re-enter secure display mode before Custos allows answers or submission again. Your previous violations remain recorded.';
      resumeSecureBtn.classList.remove('hidden');
      return;
    }
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
    securityState.resumeRequired = Boolean(data.resume_required ?? data.resumeRequired ?? securityState.resumeRequired);
    securityState.tempRemaining = Number(data.temp_remaining ?? data.tempRemaining ?? 0);
    renderSecurityOverlay();
  }

  async function triggerViolation(source) {
    if (!strictSecurity) return;
    if (!secureModeEntered || intentionalNavigation || securityState.permanent || securityState.pending || securityState.resumeRequired || securityState.tempRemaining > 0 || violationRequestInFlight) return;
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
    if (!strictSecurity) return;
    if (!secureModeEntered || intentionalNavigation || isInstalledAppMode()) return;
    if (!document.fullscreenElement) triggerViolation('fullscreen_exit');
    else if (!securityState.permanent && !securityState.resumeRequired && securityState.tempRemaining <= 0) {
      secureOverlay.classList.remove('active');
      securityOverlay.classList.remove('active');
    }
  });

  document.addEventListener('visibilitychange', async () => {
    if (!strictSecurity) return;
    if (document.hidden) {
      persistQuestionPosition(current, true);
      logBehaviorSnapshot('page_hidden');
      flushProctorEvents();
      if (secureModeEntered && !intentionalNavigation) triggerViolation('tab_hidden');
    } else {
      logEvent('tab_visible', 'Exam page became visible');
      await refreshSecurityStatus();
      if (securityState.pending) await startPendingBlackout();
    }
  });

  window.addEventListener('blur', () => {
    if (!strictSecurity) return;
    if (secureModeEntered && !intentionalNavigation) triggerViolation('window_blur');
  });
  window.addEventListener('focus', async () => {
    if (!strictSecurity) return;
    if (secureModeEntered) {
      logEvent('window_focus', 'Exam window regained focus');
      await refreshSecurityStatus();
      if (securityState.pending) await startPendingBlackout();
    }
  });

  document.addEventListener('contextmenu', e => {
    if (!strictSecurity) return;
    e.preventDefault();
    logEvent('contextmenu', 'Right-click/context menu attempt blocked');
  });

  const selectionAllowedTarget = target => Boolean(target?.closest?.('input, textarea, select, .CodeMirror, [contenteditable="true"], .exam-tools-panel'));
  document.addEventListener('selectstart', e => {
    if (!strictSecurity || selectionAllowedTarget(e.target)) return;
    e.preventDefault();
    behaviorCounters.selectionAttempts += 1;
    logEvent('selection_attempt', 'Text selection/highlight attempt blocked');
  }, true);
  document.addEventListener('dragstart', e => {
    if (!strictSecurity || selectionAllowedTarget(e.target)) return;
    e.preventDefault();
    behaviorCounters.dragAttempts += 1;
    logEvent('drag_attempt', 'Drag attempt from protected assessment content blocked');
  }, true);
  window.addEventListener('beforeprint', () => {
    if (!strictSecurity) return;
    behaviorCounters.printAttempts += 1;
    logEvent('print_attempt', 'Browser print attempt detected; assessment content is hidden from print output');
    flushProctorEvents();
  });

  document.addEventListener('keydown', e => {
    const key = e.key.toLowerCase();
    const commandKey = e.ctrlKey || e.metaKey;
    const blocked =
      e.key === 'F12' || e.key === 'F5' ||
      (e.ctrlKey && e.shiftKey && ['i', 'j', 'c', 'r'].includes(key)) ||
      (commandKey && ['a', 'u', 's', 'p', 'r', 'l', 'n', 't', 'w'].includes(key)) ||
      (e.metaKey && e.altKey && ['i', 'j', 'c'].includes(key)) ||
      (e.altKey && ['arrowleft', 'arrowright'].includes(key));
    if (strictSecurity && blocked) {
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
    if (!strictSecurity) return;
    if (!secureModeEntered || securityState.permanent || securityState.pending || securityState.resumeRequired || securityState.tempRemaining > 0) return;
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

  function logBehaviorSnapshot(reason = 'periodic') {
    if (!strictSecurity || !secureModeEntered || (document.hidden && reason === 'periodic')) return;
    const activeSeconds = behaviorCounters.activeQuestionSeconds + Math.max(0, Math.round((Date.now() - questionEnteredAt) / 1000));
    const snapshot = {
      reason,
      question: current + 1,
      answered: answeredCount(),
      flagged: flaggedCount(),
      question_changes: behaviorCounters.questionChanges,
      answer_changes: behaviorCounters.answerChanges,
      selection_attempts: behaviorCounters.selectionAttempts,
      drag_attempts: behaviorCounters.dragAttempts,
      print_attempts: behaviorCounters.printAttempts,
      active_question_seconds: activeSeconds
    };
    logEvent('behavior_snapshot', JSON.stringify(snapshot));
    behaviorCounters.questionChanges = 0;
    behaviorCounters.answerChanges = 0;
    behaviorCounters.selectionAttempts = 0;
    behaviorCounters.dragAttempts = 0;
    behaviorCounters.printAttempts = 0;
    behaviorCounters.activeQuestionSeconds = 0;
    questionEnteredAt = Date.now();
  }
  setInterval(() => logBehaviorSnapshot('periodic'), 120000);

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
    persistQuestionPosition(current, true);
    if (strictSecurity && !intentionalNavigation && (untimed || remaining > 0)) {
      logBehaviorSnapshot('page_exit');
      logEvent('beforeunload', 'Page navigation/reload initiated');
      flushProctorEvents();
    }
  });

  ['copy', 'cut', 'paste'].forEach(evt => document.addEventListener(evt, e => {
    if (!strictSecurity) return;
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
    if (!strictSecurity) return;
    if (securityState.permanent) return;
    if (securityState.tempRemaining > 0) {
      const seconds = Math.max(0, Math.ceil((temporaryLockEndsAt - Date.now()) / 1000));
      securityCountdown.textContent = String(seconds).padStart(2, '0');
      if (seconds <= 0) refreshSecurityStatus();
    }
  }, 250);

  setInterval(() => {
    if (!strictSecurity) return;
    if (securityState.permanent || securityState.pending || securityState.resumeRequired || securityState.tempRemaining > 0) refreshSecurityStatus();
  }, 5000);
  // Chat is useful during an exam, but frequent polling from every
  // student creates unnecessary database traffic. Poll quickly only while the
  // chat is open, back off while it is closed, and pause network polling when
  // the page is hidden.
  let chatPollTimer = null;
  function scheduleChatPoll(delay) {
    if (chatPollTimer) clearTimeout(chatPollTimer);
    const nextDelay = delay ?? (chatOpen ? 8000 : 30000);
    chatPollTimer = setTimeout(async () => {
      if (!document.hidden) await fetchChatMessages();
      scheduleChatPoll();
    }, nextDelay);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) fetchChatMessages();
    scheduleChatPoll(document.hidden ? 60000 : 1200);
  });
  scheduleChatPoll();

  if (strictSecurity && isInstalledAppMode()) {
    document.documentElement.classList.add('pwa-standalone');
    if (enterFullscreen) enterFullscreen.textContent = 'Begin Exam in App Mode';
    if (secureModeDescription) secureModeDescription.textContent = 'Custos detected installed app mode. Keep Custos in the foreground throughout the exam. Switching to another app, opening another browser, or leaving the exam can trigger a security violation.';
  }

  if (!strictSecurity) {
    secureOverlay?.classList.remove('active');
    securityOverlay?.classList.remove('active');
    inactiveOverlay?.classList.remove('active');
  }

  setLabToolkitOpen(false);
  updateFooterStatus();
  showQuestion(current, false);
  renderSecurityOverlay();
  fetchChatMessages();
})();
