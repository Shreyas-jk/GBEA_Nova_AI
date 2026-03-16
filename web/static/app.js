/* ================================================================
   BenefitsNavigator — Frontend Application
   ================================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  messages: [],
  programs: [],
  profile: {},
  isTyping: false,
  ws: null,
  uploadedFiles: [],   // { file_id, filename, size }
  connected: false,
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const $messages      = document.getElementById('messages');
const $typingInd     = document.getElementById('typingIndicator');
const $userInput     = document.getElementById('userInput');
const $btnSend       = document.getElementById('btnSend');
const $btnAttach     = document.getElementById('btnAttach');
const $fileInput     = document.getElementById('fileInput');
const $filePreview   = document.getElementById('filePreviewBar');
const $benefitsList  = document.getElementById('benefitsList');
const $emptyState    = document.getElementById('emptyState');
const $countBadge    = document.getElementById('countBadge');
const $benefitsFooter= document.getElementById('benefitsFooter');
const $btnActionPlan = document.getElementById('btnActionPlan');
const $benefitsPane  = document.getElementById('benefitsPane');
const $benefitsToggle= document.getElementById('benefitsToggle');
const $benefitsOverlay = document.getElementById('benefitsOverlay');
const $dropZone      = document.getElementById('dropZone');

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  state.ws = new WebSocket(`${protocol}://${location.host}/ws/chat`);

  state.ws.onopen = () => {
    state.connected = true;
  };

  state.ws.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    switch (data.type) {
      case 'agent_message':
        addAgentMessage(data.text, data.documents || []);
        break;
      case 'benefits_update':
        updateBenefitsPanel(data.programs);
        break;
      case 'typing':
        setTypingIndicator(data.active);
        break;
      case 'profile_update':
        state.profile = data.profile;
        break;
      case 'error':
        addAgentMessage(data.text || 'An error occurred.', []);
        break;
    }
  };

  state.ws.onclose = () => {
    state.connected = false;
    setTimeout(connect, 2000);
  };

  state.ws.onerror = () => {
    state.connected = false;
  };
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------
function addUserMessage(text, files) {
  const el = document.createElement('div');
  el.className = 'message user-message';
  let html = `<div class="message-content">${escapeHtml(text).replace(/\n/g, '<br>')}`;
  if (files.length) {
    html += '<div class="file-pills">';
    for (const f of files) {
      html += `<span class="file-pill">${fileIcon()} ${escapeHtml(f.filename)}</span>`;
    }
    html += '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
  $messages.appendChild(el);
  scrollToBottom();
}

function addAgentMessage(text, documents) {
  setTypingIndicator(false);

  const el = document.createElement('div');
  el.className = 'message agent-message';

  let html = `<div class="message-content">${renderMarkdown(text)}`;
  if (documents && documents.length) {
    html += '<div class="file-pills">';
    for (const name of documents) {
      html += `<span class="file-pill">${fileIcon()} ${escapeHtml(name)}</span>`;
    }
    html += '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
  $messages.appendChild(el);
  scrollToBottom();
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    $messages.scrollTop = $messages.scrollHeight;
  });
}

function setTypingIndicator(active) {
  state.isTyping = active;
  $typingInd.classList.toggle('active', active);
  if (active) scrollToBottom();
}

// ---------------------------------------------------------------------------
// Send
// ---------------------------------------------------------------------------
function sendMessage() {
  const text = $userInput.value.trim();
  if (!text && !state.uploadedFiles.length) return;
  if (!state.connected) return;

  const msg = {
    type: 'message',
    text: text,
    file_ids: state.uploadedFiles.map(f => f.file_id),
  };

  state.ws.send(JSON.stringify(msg));
  addUserMessage(text, state.uploadedFiles);

  // Clear input
  $userInput.value = '';
  autoResize();
  clearFilePreview();
}

// ---------------------------------------------------------------------------
// File Upload
// ---------------------------------------------------------------------------
const ALLOWED_TYPES = ['application/pdf', 'image/png', 'image/jpeg'];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB

async function uploadFile(file) {
  if (!ALLOWED_TYPES.includes(file.type)) {
    addAgentMessage(`**Unsupported file type:** ${file.type}. Please upload PDF, PNG, or JPG files.`, []);
    return;
  }
  if (file.size > MAX_FILE_SIZE) {
    addAgentMessage(`**File too large:** ${(file.size / 1024 / 1024).toFixed(1)} MB. Maximum size is 20 MB.`, []);
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    const data = await resp.json();

    if (data.error) {
      addAgentMessage(`**Upload error:** ${data.error}`, []);
      return;
    }

    state.uploadedFiles.push({
      file_id: data.file_id,
      filename: data.filename,
      size: data.size,
    });
    renderFilePreview();
  } catch (err) {
    addAgentMessage(`**Upload failed:** ${err.message}`, []);
  }
}

function renderFilePreview() {
  $filePreview.innerHTML = '';
  $filePreview.classList.toggle('has-files', state.uploadedFiles.length > 0);

  for (let i = 0; i < state.uploadedFiles.length; i++) {
    const f = state.uploadedFiles[i];
    const el = document.createElement('div');
    el.className = 'file-preview-item';
    el.innerHTML = `
      ${fileIcon()}
      <span>${escapeHtml(f.filename)}</span>
      <span class="remove-file" data-index="${i}" title="Remove">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5">
          <line x1="3" y1="3" x2="11" y2="11"/><line x1="11" y1="3" x2="3" y2="11"/>
        </svg>
      </span>
    `;
    $filePreview.appendChild(el);
  }

  // Bind remove handlers
  $filePreview.querySelectorAll('.remove-file').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const idx = parseInt(e.currentTarget.dataset.index);
      state.uploadedFiles.splice(idx, 1);
      renderFilePreview();
    });
  });
}

function clearFilePreview() {
  state.uploadedFiles = [];
  $filePreview.innerHTML = '';
  $filePreview.classList.remove('has-files');
}

// ---------------------------------------------------------------------------
// Benefits Panel
// ---------------------------------------------------------------------------
function updateBenefitsPanel(programs) {
  state.programs = programs;
  const eligible = programs.filter(p => p.status !== 'not_eligible');
  const count = eligible.length;

  // Update count badge
  $countBadge.textContent = count;
  $countBadge.classList.remove('pulse');
  void $countBadge.offsetWidth; // force reflow
  $countBadge.classList.add('pulse');

  // Show/hide empty state and footer
  if (programs.length === 0) {
    $emptyState.style.display = '';
    $benefitsFooter.style.display = 'none';
    return;
  }

  $emptyState.style.display = 'none';
  $benefitsFooter.style.display = count > 0 ? '' : 'none';

  // Clear existing cards
  $benefitsList.querySelectorAll('.program-card').forEach(c => c.remove());

  // Sort: likely first, then possible, then not eligible
  const order = { likely: 0, possible: 1, not_eligible: 2 };
  const sorted = [...programs].sort((a, b) => (order[a.status] ?? 1) - (order[b.status] ?? 1));

  sorted.forEach((prog, i) => {
    const card = document.createElement('div');
    card.className = `program-card ${prog.status === 'not_eligible' ? 'not-eligible' : ''}`;
    card.style.animationDelay = `${i * 0.06}s`;

    // Normalize field names — handle both old and new formats
    const name     = prog.name || prog.short_name || prog.program_name || 'Unknown';
    const category = prog.category || 'other';
    const benefit  = prog.benefit || prog.estimated_benefit || '';
    const reason   = prog.reason || '';
    const applyUrl = prog.apply_url || prog.application_url || '';

    const catClass = `cat-${category}`;
    const catLabel = category.replace(/_/g, ' ');
    const badgeClass = prog.status === 'likely' ? 'badge-likely'
      : prog.status === 'possible' ? 'badge-possible'
      : 'badge-not-eligible';
    const badgeLabel = prog.status === 'likely' ? 'Likely eligible'
      : prog.status === 'possible' ? 'May qualify'
      : 'Not eligible';

    let cardBody = `
      <div class="card-top">
        <span class="category-tag ${catClass}">
          <span class="category-dot"></span>
          ${catLabel}
        </span>
        <span class="confidence-badge ${badgeClass}">${badgeLabel}</span>
      </div>
      <div class="card-name">${escapeHtml(name)}</div>
      <div class="card-benefit">${escapeHtml(benefit)}</div>
      <div class="card-reason">${escapeHtml(reason)}</div>
    `;

    if (applyUrl && prog.status !== 'not_eligible') {
      cardBody += `<a class="card-apply-link" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener">Apply &rarr;</a>`;
    }

    card.innerHTML = cardBody;
    $benefitsList.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Action Plan
// ---------------------------------------------------------------------------
$btnActionPlan.addEventListener('click', () => {
  if (!state.connected) return;
  const text = 'Please generate a detailed action plan for applying to all the programs I may be eligible for.';
  const msg = { type: 'message', text, file_ids: [] };
  state.ws.send(JSON.stringify(msg));
  addUserMessage(text, []);
});

// ---------------------------------------------------------------------------
// Benefits panel toggle (mobile)
// ---------------------------------------------------------------------------
$benefitsToggle.addEventListener('click', () => {
  $benefitsPane.classList.toggle('open');
  $benefitsOverlay.classList.toggle('open');
});

$benefitsOverlay.addEventListener('click', () => {
  $benefitsPane.classList.remove('open');
  $benefitsOverlay.classList.remove('open');
});

// ---------------------------------------------------------------------------
// Input handling
// ---------------------------------------------------------------------------
$btnSend.addEventListener('click', sendMessage);

$userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-resize textarea
function autoResize() {
  $userInput.style.height = 'auto';
  $userInput.style.height = Math.min($userInput.scrollHeight, 140) + 'px';
}
$userInput.addEventListener('input', autoResize);

// Attach button
$btnAttach.addEventListener('click', () => $fileInput.click());

$fileInput.addEventListener('change', () => {
  for (const file of $fileInput.files) {
    uploadFile(file);
  }
  $fileInput.value = '';
});

// Paste handler
document.addEventListener('paste', (e) => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.kind === 'file') {
      const file = item.getAsFile();
      if (file) uploadFile(file);
    }
  }
});

// Drag and drop
let dragCounter = 0;

document.addEventListener('dragenter', (e) => {
  e.preventDefault();
  dragCounter++;
  if (e.dataTransfer?.types.includes('Files')) {
    $dropZone.classList.add('active');
  }
});

document.addEventListener('dragleave', (e) => {
  e.preventDefault();
  dragCounter--;
  if (dragCounter <= 0) {
    dragCounter = 0;
    $dropZone.classList.remove('active');
  }
});

document.addEventListener('dragover', (e) => e.preventDefault());

document.addEventListener('drop', (e) => {
  e.preventDefault();
  dragCounter = 0;
  $dropZone.classList.remove('active');
  const files = e.dataTransfer?.files;
  if (files) {
    for (const file of files) uploadFile(file);
  }
});

// ---------------------------------------------------------------------------
// Markdown rendering (lightweight)
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Headers
  html = html.replace(/^### (.+)$/gm, '<strong>$1</strong>');
  html = html.replace(/^## (.+)$/gm, '<strong>$1</strong>');
  html = html.replace(/^# (.+)$/gm, '<strong>$1</strong>');
  // Unordered lists
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Line breaks
  html = html.replace(/\n/g, '<br>');
  // Clean up double breaks in lists
  html = html.replace(/<\/li><br><li>/g, '</li><li>');
  html = html.replace(/<\/ul><br>/g, '</ul>');
  html = html.replace(/<br><ul>/g, '<ul>');

  return html;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function fileIcon() {
  return '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M8 1H3.5A1.5 1.5 0 0 0 2 2.5v9A1.5 1.5 0 0 0 3.5 13h7a1.5 1.5 0 0 0 1.5-1.5V5L8 1z"/><polyline points="8 1 8 5 12 5"/></svg>';
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
connect();
$userInput.focus();
