/**
 * Gonitor AI Chat Panel
 *
 * Design:
 *  - Session isolation: each (hostId, serviceType) pair has its own messages[] array
 *    stored in `AIChatPanel.sessions` keyed by `${hostId}_${serviceType}`.
 *  - Stateless backend: the frontend owns history, sends full session array per request.
 *  - Markdown-lite rendering: **bold**, `code`, ```blocks```, and line breaks.
 *  - Auto-scroll, loading indicator, graceful error display.
 *
 * Public API:
 *   openAIChat(context, initialMessage)   — opens the panel, optionally fires first message
 *   closeAIChat()                         — closes the panel
 */

const AIChatPanel = (() => {
  // ── Session store: keyed by "${hostId}_${serviceType}" ─────────────────────
  const sessions = {};

  let currentSessionKey = "";
  let currentContext = null;
  let isOpen = false;
  let isLoading = false;

  // ── DOM references (populated on first open) ──────────────────────────────
  let panel, overlay, messagesEl, inputEl, sendBtn, sessionLabel;

  // ── Markdown-lite renderer ─────────────────────────────────────────────────
  function renderMarkdown(text) {
    if (!text) return "";
    let html = escHtml(text);

    // Fenced code blocks  ```lang\ncode\n```
    html = html.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
      `<pre class="ai-code-block"><code>${code.trim()}</code></pre>`
    );

    // Inline code `foo`
    html = html.replace(/`([^`]+)`/g, '<code class="ai-inline-code">$1</code>');

    // Bold **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Line breaks → <br> (but not inside pre blocks)
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  function escHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Create panel DOM (once) ───────────────────────────────────────────────
  function buildPanel() {
    if (document.getElementById("ai-chat-panel")) return;

    // Overlay
    overlay = document.createElement("div");
    overlay.id = "ai-chat-overlay";
    overlay.onclick = close;
    document.body.appendChild(overlay);

    // Panel
    panel = document.createElement("div");
    panel.id = "ai-chat-panel";
    panel.innerHTML = `
      <div class="ai-panel-header">
        <div class="ai-panel-title">
          <span class="ai-panel-icon">✦</span>
          <span>Gonitor AI Copilot</span>
        </div>
        <div class="ai-panel-meta">
          <span id="ai-session-label" class="ai-session-label"></span>
          <button id="ai-clear-btn" class="ai-icon-btn" title="Clear chat" onclick="AIChatPanel.clearSession()">
            <i class="bi bi-trash3"></i>
          </button>
          <button class="ai-icon-btn" title="Close" onclick="AIChatPanel.close()">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      </div>
      <div id="ai-messages" class="ai-messages"></div>
      <div class="ai-input-area">
        <textarea
          id="ai-input"
          class="ai-textarea"
          placeholder="Ask anything about this check..."
          rows="2"
        ></textarea>
        <button id="ai-send-btn" class="ai-send-btn" onclick="AIChatPanel.send()">
          <i class="bi bi-send-fill"></i>
        </button>
      </div>
    `;
    document.body.appendChild(panel);

    messagesEl   = document.getElementById("ai-messages");
    inputEl      = document.getElementById("ai-input");
    sendBtn      = document.getElementById("ai-send-btn");
    sessionLabel = document.getElementById("ai-session-label");

    // Send on Enter (Shift+Enter = newline)
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
  }

  // ── Render a single message bubble ───────────────────────────────────────
  function appendMessage(role, content) {
    const div = document.createElement("div");
    div.className = `ai-msg ai-msg-${role}`;
    div.innerHTML = `
      <div class="ai-msg-bubble">${renderMarkdown(content)}</div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  // ── Loading indicator ─────────────────────────────────────────────────────
  function showLoading() {
    const div = document.createElement("div");
    div.className = "ai-msg ai-msg-assistant";
    div.id = "ai-loading-bubble";
    div.innerHTML = `
      <div class="ai-msg-bubble ai-loading">
        <span class="ai-dot"></span><span class="ai-dot"></span><span class="ai-dot"></span>
      </div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function removeLoading() {
    const el = document.getElementById("ai-loading-bubble");
    if (el) el.remove();
  }

  // ── Render all messages for the current session ───────────────────────────
  function renderSession() {
    if (!messagesEl) return;
    messagesEl.innerHTML = "";
    const msgs = sessions[currentSessionKey] || [];
    if (msgs.length === 0) {
      messagesEl.innerHTML = `
        <div class="ai-empty">
          <div class="ai-empty-icon">✦</div>
          <p>Ask me anything about this health check — errors, SSL certificates, DNS failures, and more.</p>
        </div>`;
    } else {
      msgs.forEach((m) => appendMessage(m.role, m.content));
    }
  }

  // ── Send a message ────────────────────────────────────────────────────────
  async function send(overrideText) {
    if (isLoading) return;
    const text = (overrideText ?? inputEl.value).trim();
    if (!text) return;

    if (!overrideText) inputEl.value = "";

    // Add user message to session
    const session = sessions[currentSessionKey] || [];
    session.push({ role: "user", content: text });
    sessions[currentSessionKey] = session;

    appendMessage("user", text);

    isLoading = true;
    sendBtn.disabled = true;
    showLoading();

    try {
      const res = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: session,
          context: currentContext,
          session_key: currentSessionKey,
        }),
      });

      const data = await res.json();
      removeLoading();

      const reply = data.reply || "⚠️ Empty response from AI.";
      session.push({ role: "assistant", content: reply });
      sessions[currentSessionKey] = session;
      appendMessage("assistant", reply);
    } catch (err) {
      removeLoading();
      appendMessage("assistant", `⚠️ Network error: ${err.message}`);
    } finally {
      isLoading = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // ── Public: open panel ────────────────────────────────────────────────────
  function open(context, initialMessage) {
    buildPanel();

    currentContext = context || null;

    // Compute session key
    const hostId      = context?.host_id      ?? "0";
    const serviceType = context?.service_type  ?? "general";
    currentSessionKey = `${hostId}_${serviceType}`;

    // Update session label
    if (sessionLabel) {
      const label = context
        ? `${context.host_name || "Host"} · ${serviceType.toUpperCase()}`
        : "General";
      sessionLabel.textContent = label;
    }

    // Show panel + overlay
    panel.classList.add("open");
    overlay.classList.add("open");
    isOpen = true;

    renderSession();
    inputEl.focus();

    // Fire automatic first message if provided and session is fresh
    const session = sessions[currentSessionKey] || [];
    if (initialMessage && session.length === 0) {
      send(initialMessage);
    }
  }

  // ── Public: close panel ───────────────────────────────────────────────────
  function close() {
    if (!panel) return;
    panel.classList.remove("open");
    overlay.classList.remove("open");
    isOpen = false;
  }

  // ── Public: clear current session ────────────────────────────────────────
  function clearSession() {
    sessions[currentSessionKey] = [];
    renderSession();
  }

  // ── Expose public API ─────────────────────────────────────────────────────
  return { open, close, send, clearSession, sessions };
})();

// Global convenience wrappers (called from HTML onclick attributes)
function openAIChat(context, initialMessage) { AIChatPanel.open(context, initialMessage); }
function closeAIChat() { AIChatPanel.close(); }
