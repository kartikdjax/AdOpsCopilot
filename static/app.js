// AI Analytics Copilot - frontend. No framework, no build step - deliberately,
// so a customer can deploy this by running the Python backend alone, nothing
// else to install.

const authScreen = document.getElementById("auth-screen");
const appEl = document.getElementById("app");
const authError = document.getElementById("auth-error");

const sidebar = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebar-overlay");

const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const newChatBtn = document.getElementById("new-chat-btn");
const historyList = document.getElementById("history-list");
const modeEyebrow = document.getElementById("mode-eyebrow");
const convTitle = document.getElementById("conv-title");

const MODE_META = {
  revive: {
    label: "Revive",
    subtitle: "Ad server: delivery, revenue, setup and changes",
    heading: "Ask about your ad server",
    placeholder: "Ask about zones, campaigns, websites, pacing or changes...",
    suggestions: [
      { label: "What's broken?", q: "What's wrong with the ad server right now?" },
      { label: "Lowest fill rate", q: "Which zones have the lowest fill rate this month?" },
      { label: "Behind pace", q: "Which campaigns are behind on their booked impressions?" },
      { label: "Margin by website", q: "What's the margin by website over the last 30 days?" },
      { label: "Recent changes", q: "What changed in the ad server in the last 2 days?" },
      { label: "Maintenance status", q: "Is Revive's maintenance running, and how fresh is the data?" },
    ],
  },
  exchange: {
    label: "Exchange",
    subtitle: "RTB / programmatic exchange data",
    heading: "Ask about exchange performance or policy",
    placeholder: "Ask about partners, win rate, timeouts or health...",
    suggestions: [
      { label: "Exchange health", q: "What is the current exchange health?" },
      { label: "Supply/demand analysis", q: "Show me the supply-demand cross analysis" },
      { label: "Generate a report", q: "Generate an exchange report for today" },
      { label: "Investigate fill rate", q: "Why did fill rate change recently?" },
    ],
  },
};

// Sample questions shown on each MCP tool's "Try a question" button, keyed
// by the tool's real name (from /mcp/tools) rather than any guessed set.
const SAMPLE_FOR_TOOL = {
  list_available_metrics: "What metrics are available?",
  get_metric_definition: "How is fill rate calculated?",
  list_entities: "Which websites does each manager own?",
  get_data_freshness: "Is Revive's maintenance running, and how fresh is the data?",
  calculate_kpi: "What were revenue, cost and margin over the last 30 days?",
  compare_periods: "How did the last 7 days compare with the 7 days before?",
  rank_entities: "Which zones have the lowest fill rate this month?",
  analyze_trend: "Is fill rate trending up or down for Zone_3_fill_rate_decline?",
  detect_anomalies: "Were there any unusual days for impressions in the last 30 days?",
  explain_metric_change: "Why did Zone_3_fill_rate_decline's fill rate drop?",
  search_knowledge_base: "What should I check before changing a campaign's priority?",
  generate_revive_report: "Give me a full report on Website_1.",
  get_banner_zone_mapping: "Which banners run in Zone_2_under_monetized?",
  inspect_revive_object: "What's the priority, weight and capping on Advertiser_2_Campaign_1?",
  run_revive_check: "What's wrong with the ad server right now?",
  get_revive_audit_log: "Who paused Advertiser_2_Campaign_2, and when?",
  generate_exchange_report: "Generate an exchange report for today.",
  get_realtime_exchange_health: "What is the current exchange health?",
  get_supply_demand_cross_analysis: "Show me the supply-demand cross analysis.",
};

// Tools panel sections, in display order. A tool's domain comes from
// /mcp/tools (null = shared by both modes).
const TOOL_SECTIONS = [
  { domain: "core", title: "Both modes", note: "Metrics, rankings, trends and playbooks - loaded in Revive and Exchange." },
  { domain: "revive", title: "Revive only", note: "Reports, setup inspection, health checks and the audit log for your ad server." },
  { domain: "exchange", title: "Exchange only", note: "Partner reports, live health and supply-demand analysis." },
];

// Revive access, from the user's role. Pending users can use Exchange but
// not Revive; the server enforces this too - the UI just explains it.
function hasReviveAccess() {
  return currentUser?.role === "admin" || currentUser?.role === "manager";
}

function applyAccessState() {
  const blocked = currentMode === "revive" && !hasReviveAccess();
  chatInput.disabled = blocked;
  sendBtn.disabled = blocked;
  chatInput.placeholder = blocked
    ? "Revive access needed - ask a Copilot admin to grant it"
    : MODE_META[currentMode].placeholder;
}

function roleLabel(user) {
  if (user.role === "admin") return "Admin · all of Revive";
  if (user.role === "manager") return `Manager · ${user.agency_name || `manager ${user.agency_id}`}`;
  return "Pending access";
}

let currentUser = null;
let currentMode = localStorage.getItem("copilot_mode") || "revive";
let currentChatId = null;

// --- Session-id helpers (one active thread per mode, remembered locally) --
function sessionKey(mode) {
  return `copilot_session_${mode}`;
}
function getOrCreateSessionId(mode) {
  let id = localStorage.getItem(sessionKey(mode));
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(sessionKey(mode), id);
  }
  return id;
}
function setActiveSessionId(mode, id) {
  currentChatId = id;
  localStorage.setItem(sessionKey(mode), id);
}

// --- Fetch helper --------------------------------------------------------
// Paths are relative ("chat", not "/chat") so the app also works when a proxy
// serves it under a prefix such as /copilot/.
async function api(path, options = {}) {
  const resp = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return resp;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// --- Minimal markdown rendering -------------------------------------------
// The LLM's answers use markdown (tables, **bold**, headers, bullets).
// A tiny hand-rolled renderer covers what we actually see in practice,
// without pulling in a markdown library for a handful of patterns.
function renderMarkdown(text) {
  const lines = text.split("\n");
  let html = "";
  let inTable = false;
  let tableRows = [];

  function flushTable() {
    if (tableRows.length === 0) return;
    const [headerRow, , ...bodyRows] = tableRows; // skip the |---|---| separator row
    html += "<table><thead><tr>";
    headerRow.split("|").map((c) => c.trim()).filter(Boolean).forEach((cell) => {
      html += `<th>${cell}</th>`;
    });
    html += "</tr></thead><tbody>";
    bodyRows.forEach((row) => {
      html += "<tr>";
      row.split("|").map((c) => c.trim()).filter(Boolean).forEach((cell) => {
        html += `<td>${inlineFormat(cell)}</td>`;
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    tableRows = [];
  }

  function inlineFormat(s) {
    return s
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }

  for (const line of lines) {
    if (line.trim().startsWith("|")) {
      inTable = true;
      tableRows.push(line.trim());
      continue;
    }
    if (inTable) {
      flushTable();
      inTable = false;
    }

    if (line.startsWith("### ")) html += `<h4>${inlineFormat(line.slice(4))}</h4>`;
    else if (line.startsWith("## ")) html += `<h3>${inlineFormat(line.slice(3))}</h3>`;
    else if (line.startsWith("# ")) html += `<h2>${inlineFormat(line.slice(2))}</h2>`;
    else if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
      html += `<li>${inlineFormat(line.trim().slice(2))}</li>`;
    } else if (line.trim() === "") {
      html += "<br>";
    } else if (line.trim() === "---") {
      html += "<hr>";
    } else {
      html += `<div>${inlineFormat(line)}</div>`;
    }
  }
  flushTable();
  return html;
}

// --- Message rendering -----------------------------------------------------
function clearChatLog() {
  chatLog.innerHTML = "";
}

function setConvTitle(title) {
  convTitle.textContent = title || "New conversation";
}

function renderWelcome() {
  clearChatLog();
  setConvTitle(null);
  const meta = MODE_META[currentMode];
  const chips = meta.suggestions
    .map((s) => `<button class="suggestion-chip" data-q="${escapeAttr(s.q)}">${escapeHtml(s.label)}</button>`)
    .join("");
  const welcome = document.createElement("div");
  welcome.className = "welcome";
  welcome.id = "welcome";
  if (currentMode === "revive" && !hasReviveAccess()) {
    welcome.innerHTML = `
      <h2>${meta.heading}</h2>
      <div class="access-notice">
        <strong>Your account doesn't have Revive access yet.</strong>
        <span>Ask a Copilot admin to grant you the admin or manager role. You can use Exchange in the meantime.</span>
      </div>`;
    chatLog.appendChild(welcome);
    return;
  }
  const scopeNote = currentMode === "revive" && currentUser?.role === "manager"
    ? `<p class="scope-note">Showing only ${escapeHtml(currentUser.agency_name || "your manager's")} advertisers, websites and users.</p>`
    : "";
  welcome.innerHTML = `
    <h2>${meta.heading}</h2>
    ${scopeNote}
    <div class="suggestions">${chips}</div>`;
  chatLog.appendChild(welcome);
  welcome.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.q));
  });
}

function appendMessage(role, content, toolCalls) {
  document.getElementById("welcome")?.remove();

  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.textContent = content;
  }
  wrapper.appendChild(bubble);

  if (toolCalls && toolCalls.length > 0) {
    const badges = document.createElement("div");
    badges.className = "tool-badges";
    toolCalls.forEach((name) => {
      const badge = document.createElement("span");
      badge.className = "tool-badge";
      badge.textContent = name;
      badges.appendChild(badge);
    });
    wrapper.appendChild(badges);
  }

  chatLog.appendChild(wrapper);
  chatLog.scrollTop = chatLog.scrollHeight;
  return wrapper;
}

function appendTypingIndicator() {
  const wrapper = document.createElement("div");
  wrapper.className = "message assistant";
  wrapper.id = "typing-indicator";
  wrapper.innerHTML = `<div class="bubble"><div class="typing-indicator"><span></span><span></span><span></span></div></div>`;
  chatLog.appendChild(wrapper);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function removeTypingIndicator() {
  document.getElementById("typing-indicator")?.remove();
}

function renderChatMessages(chat) {
  clearChatLog();
  const messages = chat.messages || [];
  messages.forEach((m, idx) => {
    const isLastAssistant = m.role === "assistant" && idx === messages.length - 1;
    appendMessage(m.role, m.content, isLastAssistant ? chat.tool_calls_made : null);
  });
  if (messages.length === 0) {
    renderWelcome();
  } else {
    setConvTitle(chat.title);
  }
}

// --- Chat history sidebar --------------------------------------------------
function formatTimestamp(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

async function refreshHistory() {
  const resp = await api("history");
  if (!resp.ok) return [];
  const { chats } = await resp.json();
  historyList.innerHTML = "";
  if (chats.length === 0) {
    historyList.innerHTML = `<div class="history-empty">No conversations yet</div>`;
    return chats;
  }
  chats.forEach((chat) => {
    const item = document.createElement("div");
    item.className = "history-item" + (chat.id === currentChatId ? " active" : "");
    item.innerHTML = `
      <span class="history-mode-dot ${chat.mode}"></span>
      <div class="history-item-text">
        <div class="history-item-title">${escapeHtml(chat.title)}</div>
        <div class="history-item-meta">${MODE_META[chat.mode]?.label || chat.mode} &middot; ${formatTimestamp(chat.updated_at)}</div>
      </div>
      <button type="button" class="history-delete" title="Delete conversation">&times;</button>`;
    item.querySelector(".history-item-text").addEventListener("click", () => loadChat(chat.id, chat.mode));
    item.querySelector(".history-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(chat.id, chat.mode);
    });
    historyList.appendChild(item);
  });
  return chats;
}

async function loadChat(chatId, mode) {
  if (mode !== currentMode) setMode(mode, { skipSessionSwap: true });
  setActiveSessionId(mode, chatId);
  setPanel("chats");
  const resp = await api(`history/${chatId}`);
  if (!resp.ok) {
    renderWelcome();
  } else {
    renderChatMessages(await resp.json());
  }
  await refreshHistory();
}

async function deleteChat(chatId, mode) {
  await api(`history/${chatId}`, { method: "DELETE" }).catch(() => {});
  if (chatId === currentChatId) {
    startNewChat(mode, { silent: true });
  }
  await refreshHistory();
}

function startNewChat(mode, { silent = false } = {}) {
  const id = crypto.randomUUID();
  setActiveSessionId(mode, id);
  setPanel("chats");
  renderWelcome();
  if (!silent) refreshHistory();
}

// --- Mode switching ---------------------------------------------------------
function setMode(mode, { skipSessionSwap = false } = {}) {
  currentMode = mode;
  localStorage.setItem("copilot_mode", mode);
  document.querySelectorAll(".mode-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
  modeEyebrow.textContent = `${MODE_META[mode].label} · ${MODE_META[mode].subtitle}`;
  applyAccessState();

  if (!skipSessionSwap) {
    loadActiveChatOrWelcome(mode);
  }
}

async function loadActiveChatOrWelcome(mode) {
  const id = getOrCreateSessionId(mode);
  currentChatId = id;
  const resp = await api(`history/${id}`);
  if (resp.ok) {
    renderChatMessages(await resp.json());
  } else {
    renderWelcome();
  }
  await refreshHistory();
}

document.querySelectorAll(".mode-tab").forEach((btn) => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

// --- Chat input: auto-growing textarea, Enter to send ------------------------
function autoGrowInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + "px";
}
chatInput.addEventListener("input", autoGrowInput);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

function prefillAndFocus(text) {
  setPanel("chats");
  chatInput.value = text;
  autoGrowInput();
  chatInput.focus();
}

// --- Sending messages --------------------------------------------------------
async function sendMessage(text) {
  appendMessage("user", text);
  chatInput.value = "";
  autoGrowInput();
  sendBtn.disabled = true;
  appendTypingIndicator();

  try {
    const resp = await api("chat", {
      method: "POST",
      body: JSON.stringify({ session_id: currentChatId, message: text, mode: currentMode }),
    });

    removeTypingIndicator();

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
      appendMessage("error", `Error: ${err.detail || resp.statusText}`);
      return;
    }

    const data = await resp.json();
    appendMessage("assistant", data.answer, data.tool_calls_made);
    const chats = await refreshHistory();
    const entry = chats.find((c) => c.id === currentChatId);
    if (entry) setConvTitle(entry.title);
  } catch (e) {
    removeTypingIndicator();
    appendMessage("error", `Connection error: ${e.message}. Is the backend running?`);
  } finally {
    applyAccessState();
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (text) sendMessage(text);
});

newChatBtn.addEventListener("click", () => startNewChat(currentMode));

// --- Panel switching (Chats / MCP tools / Take a tour) -----------------------
function setPanel(name) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.panel === name));
  closeSidebar();
  if (name === "tools") loadToolsPanel();
  if (name === "tour") loadTourPanel();
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => setPanel(btn.dataset.panel));
});

// --- MCP tools panel -----------------------------------------------------------
let toolsLoaded = false;

async function loadToolsPanel() {
  const toolsList = document.getElementById("tools-list");
  if (toolsLoaded) return;
  const resp = await api("mcp/tools");
  if (!resp.ok) {
    toolsList.innerHTML = `<div class="loading">Could not load tools.</div>`;
    return;
  }
  const { tools, message } = await resp.json();
  if (message && tools.length === 0) {
    toolsList.innerHTML = `<div class="loading">${escapeHtml(message)}</div>`;
    return;
  }
  toolsLoaded = true;
  const card = (t, domain) => {
    const sample = SAMPLE_FOR_TOOL[t.name] || "What can you tell me about current performance?";
    return `
      <article class="tool-card">
        <div class="tool-card-head">
          <span class="tool-card-name">${escapeHtml(t.name)}</span>
          <span class="tool-card-domain domain-${domain}">${domain === "core" ? "both" : domain}</span>
        </div>
        <div class="tool-card-guidance">${escapeHtml(t.guidance)}</div>
        <details class="tool-card-details">
          <summary>Technical description</summary>
          <div class="tool-card-desc">${escapeHtml(t.description)}</div>
        </details>
        <button type="button" class="try-tool" data-mode="${domain}" data-q="${escapeAttr(sample)}">Try a question &rarr;</button>
      </article>`;
  };
  toolsList.innerHTML = TOOL_SECTIONS.map((section) => {
    const inSection = tools.filter((t) => (t.domain || "core") === section.domain);
    if (inSection.length === 0) return "";
    return `
      <div class="tool-section-head">
        <h3>${section.title} <span class="tool-count">${inSection.length}</span></h3>
        <p>${section.note}</p>
      </div>
      ${inSection.map((t) => card(t, section.domain)).join("")}`;
  }).join("");
  toolsList.querySelectorAll(".try-tool").forEach((btn) => {
    btn.addEventListener("click", () => {
      // A mode-specific tool only exists in its own mode.
      if (btn.dataset.mode !== "core" && btn.dataset.mode !== currentMode) setMode(btn.dataset.mode);
      prefillAndFocus(btn.dataset.q);
    });
  });
}

// --- Take a tour panel -----------------------------------------------------------
let tourSteps = [];

async function loadTourPanel() {
  const el = document.getElementById("tour-content");
  if (tourSteps.length === 0) {
    const resp = await api("tour");
    if (!resp.ok) {
      el.innerHTML = `<div class="loading">Could not load the tour.</div>`;
      return;
    }
    const data = await resp.json();
    tourSteps = data.steps || [];
  }
  el.innerHTML = `<div class="tour-track">${tourSteps
    .map(
      (s, i) => `
    <article class="tour-step">
      <div class="step-number">${i + 1}</div>
      <div>
        <h3>${escapeHtml(s.title)}</h3>
        <p>${escapeHtml(s.body)}</p>
        ${
          s.sample
            ? `<div class="sample">
          <span>Sample workflow</span>
          <strong>${escapeHtml(s.sample)}</strong>
          <button type="button" class="run-sample" data-step="${escapeAttr(s.id)}" data-q="${escapeAttr(s.sample)}">Try it &rarr;</button>
        </div>`
            : ""
        }
      </div>
    </article>`
    )
    .join("")}</div>`;
  el.querySelectorAll(".run-sample").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.step === "scope") setMode("exchange");
      prefillAndFocus(btn.dataset.q);
    });
  });
}

// --- Mobile sidebar drawer ------------------------------------------------------
function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("visible");
}
document.getElementById("open-sidebar").addEventListener("click", () => {
  sidebar.classList.add("open");
  sidebarOverlay.classList.add("visible");
});
document.getElementById("close-sidebar").addEventListener("click", closeSidebar);
sidebarOverlay.addEventListener("click", closeSidebar);

// --- Auth ------------------------------------------------------------------
const signinForm = document.getElementById("signin-form");

function showAuthError(msg) {
  authError.textContent = msg;
  authError.hidden = false;
}

signinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.hidden = true;
  const email = document.getElementById("signin-email").value;
  const password = document.getElementById("signin-password").value;
  const resp = await api("auth/signin", { method: "POST", body: JSON.stringify({ email, password }) });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Sign in failed" }));
    showAuthError(err.detail || "Sign in failed");
    return;
  }
  // /auth/me carries the manager's name as well as the role. It also proves
  // the browser kept the session cookie: if it didn't (for example the app was
  // opened at an address its cookie doesn't cover), every later request would
  // fail with "Sign in required", so say so now instead of showing the app.
  const me = await api("auth/me");
  if (!me.ok) {
    showAuthError("Your password was accepted, but your browser didn't keep the session. " +
                  "Open the Copilot at its usual address and sign in again.");
    return;
  }
  const { user } = await me.json();
  onAuthenticated(user);
});

document.getElementById("signout-btn").addEventListener("click", async () => {
  await api("auth/signout", { method: "POST" }).catch(() => {});
  currentUser = null;
  appEl.hidden = true;
  authScreen.hidden = false;
  signinForm.reset();
});

function onAuthenticated(user) {
  currentUser = user;
  authScreen.hidden = true;
  appEl.hidden = false;
  document.getElementById("user-name").textContent = user.display_name;
  document.getElementById("user-email").textContent = user.email;
  const roleEl = document.getElementById("user-role");
  roleEl.textContent = roleLabel(user);
  roleEl.className = `user-role role-${user.role || "pending"}`;
  document.getElementById("user-avatar").textContent = (user.display_name || "U").charAt(0).toUpperCase();
  setMode(currentMode);
}

// --- Boot --------------------------------------------------------------------
(async function init() {
  const resp = await api("auth/me");
  if (resp.ok) {
    const { user } = await resp.json();
    onAuthenticated(user);
  } else {
    authScreen.hidden = false;
  }
})();
