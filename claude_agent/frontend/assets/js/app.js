import {
  clearSession,
  confirmChat,
  createSession,
  getConfigFile,
  getSessionMessages,
  getUserMemoryFile,
  listSessions,
  listUsers,
  saveUserMemoryFile,
  sendChat,
} from "./api.js";
import { appendMessage, permissionPrompt, renderMessages, setOptions, setStatus, toast } from "./ui.js";

const els = {
  topUserId: document.getElementById("topUserId"),
  topSessionCreatedAt: document.getElementById("topSessionCreatedAt"),
  topClock: document.getElementById("topClock"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),

  exportBtn: document.getElementById("exportBtn"),
  clearBtn: document.getElementById("clearBtn"),

  userSelect: document.getElementById("userSelect"),
  sessionSearch: document.getElementById("sessionSearch"),
  sessionList: document.getElementById("sessionList"),
  newSessionId: document.getElementById("newSessionId"),
  createSessionBtn: document.getElementById("createSessionBtn"),

  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatInner: document.getElementById("chatInner"),
  chatLog: document.getElementById("chatLog"),

  refreshFilesBtn: document.getElementById("refreshFilesBtn"),
  fileList: document.getElementById("fileList"),

  drawer: document.getElementById("drawer"),
  drawerPath: document.getElementById("drawerPath"),
  drawerEditor: document.getElementById("drawerEditor"),
  drawerGutter: document.getElementById("drawerGutter"),
  drawerCloseBtn: document.getElementById("drawerCloseBtn"),
  drawerSaveBtn: document.getElementById("drawerSaveBtn"),

  toastHost: document.getElementById("toastHost"),
};

const state = {
  userId: "",
  sessionId: "",
  sessions: [],
  messages: [],
  createdAt: "",
  openedFile: null,
};

function nowClockText() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function updateClock() {
  els.topClock.textContent = nowClockText();
}

function safeParseJson(text) {
  try {
    return JSON.parse(String(text || ""));
  } catch {
    return null;
  }
}

function renderSessionList() {
  const q = String(els.sessionSearch.value || "").trim().toLowerCase();
  const filtered = (state.sessions || []).filter((s) => {
    const id = String(s.session_id || "");
    const preview = String(s.preview || "");
    if (!q) return true;
    return id.toLowerCase().includes(q) || preview.toLowerCase().includes(q);
  });

  els.sessionList.innerHTML = "";
  for (const s of filtered) {
    const item = document.createElement("div");
    item.className = "session-item" + (String(s.session_id) === state.sessionId ? " active" : "");
    item.dataset.sessionId = String(s.session_id || "");

    const id = document.createElement("div");
    id.className = "session-id";
    id.textContent = String(s.session_id || "");

    const preview = document.createElement("div");
    preview.className = "session-preview";
    preview.textContent = String(s.preview || "").trim() || "（暂无内容）";

    item.appendChild(id);
    item.appendChild(preview);
    item.addEventListener("click", async () => {
      const sid = String(s.session_id || "");
      if (!sid) return;
      state.sessionId = sid;
      await loadSessionMessages();
      renderSessionList();
      await refreshFiles();
    });

    els.sessionList.appendChild(item);
  }
}

function updateTopBar() {
  els.topUserId.textContent = state.userId || "-";
  els.topSessionCreatedAt.textContent = state.createdAt ? `created: ${state.createdAt}` : "-";
}

async function refreshUsers() {
  const data = await listUsers();
  const users = data.users || [];
  const opts = users.length ? users : ["default"];
  setOptions(els.userSelect, opts);
  state.userId = els.userSelect.value || "default";
  updateTopBar();
}

async function refreshSessions() {
  if (!state.userId) {
    state.sessions = [];
    state.sessionId = "";
    renderSessionList();
    return;
  }
  const data = await listSessions(state.userId);
  const sessions = data.sessions || [];
  state.sessions = [...sessions].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  if (!state.sessionId && state.sessions.length) state.sessionId = String(state.sessions[0]?.session_id || "");
  if (!state.sessionId && !state.sessions.length) {
    const sid = `s_${new Date().toISOString().replaceAll(":", "").replaceAll("-", "").slice(0, 15)}`;
    await createSession(state.userId, sid);
    const data2 = await listSessions(state.userId);
    const sessions2 = data2.sessions || [];
    state.sessions = [...sessions2].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    state.sessionId = sid;
  }
  renderSessionList();
}

async function loadSessionMessages() {
  if (!state.userId || !state.sessionId) {
    state.messages = [];
    state.createdAt = "";
    renderMessages(els.chatInner, []);
    updateTopBar();
    return;
  }
  const data = await getSessionMessages(state.userId, state.sessionId);
  state.messages = data.messages || [];
  state.createdAt = String(data.created_at || "");
  renderMessages(els.chatInner, state.messages);
  updateTopBar();
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function buildMarkdownExport(messages) {
  const lines = [];
  lines.push(`# Chat Export`);
  lines.push(``);
  lines.push(`- user_id: ${state.userId}`);
  lines.push(`- session_id: ${state.sessionId}`);
  if (state.createdAt) lines.push(`- created_at: ${state.createdAt}`);
  lines.push(``);
  for (const m of messages || []) {
    const role = String(m?.role || "");
    const content = String(m?.content || "");
    lines.push(`## ${role}`);
    lines.push(``);
    lines.push(content);
    lines.push(``);
  }
  return lines.join("\n");
}

function downloadTextFile(filename, content) {
  const blob = new Blob([String(content || "")], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function updateGutter(text) {
  const lines = String(text || "").split("\n").length;
  const nums = [];
  for (let i = 1; i <= lines; i++) nums.push(String(i));
  els.drawerGutter.textContent = nums.join("\n");
}

function openDrawer({ path, content, editable, kind }) {
  state.openedFile = { path, kind, editable: !!editable };
  els.drawerPath.textContent = String(path || "-");
  els.drawerPath.title = String(path || "");
  els.drawerEditor.value = String(content || "");
  els.drawerEditor.readOnly = !editable;
  els.drawerSaveBtn.style.display = editable ? "inline-flex" : "none";
  updateGutter(els.drawerEditor.value);
  els.drawer.classList.add("open");
  els.drawerEditor.scrollTop = 0;
  els.drawerGutter.scrollTop = 0;
}

function closeDrawer() {
  state.openedFile = null;
  els.drawer.classList.remove("open");
}

async function refreshFiles() {
  if (!state.userId) {
    els.fileList.innerHTML = "";
    return;
  }
  const items = [];
  const cfg = await getConfigFile();
  items.push({ name: "config.py", kind: "config", path: cfg.path, content: cfg.content, editable: false });
  const mem = await getUserMemoryFile(state.userId);
  items.push({ name: "MEMORY.md", kind: "memory", path: mem.path, content: mem.content, editable: true });

  els.fileList.innerHTML = "";
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "file-item";

    const name = document.createElement("div");
    name.className = "file-name";
    name.textContent = it.name;

    const path = document.createElement("div");
    path.className = "file-path";
    path.textContent = it.path;
    path.title = it.path;

    row.appendChild(name);
    row.appendChild(path);
    row.addEventListener("click", () => openDrawer(it));
    els.fileList.appendChild(row);
  }
}

async function handleReply(replyText) {
  const obj = safeParseJson(replyText);
  if (obj && typeof obj === "object" && obj.decision === "confirm") {
    setStatus(els.statusDot, els.statusText, "tool");
    const yes = await permissionPrompt(els.toastHost, {
      title: "需要确认",
      body: `${String(obj.tool || "")}\n${String(obj.reason || "")}\n${String(obj.normalized || "")}`.trim(),
      yesText: "确认执行",
      noText: "拒绝",
    });
    const data = await confirmChat(state.userId, state.sessionId, yes);
    await loadSessionMessages();
    setStatus(els.statusDot, els.statusText, "idle");
    await handleReply(data.reply || "");
    return;
  }
  if (obj && typeof obj === "object" && obj.decision === "deny") {
    toast(els.toastHost, String(obj.reason || "已拒绝"), { variant: "warn" });
  }
}

function bindEvents() {
  els.userSelect.addEventListener("change", async () => {
    state.userId = els.userSelect.value || "";
    state.sessionId = "";
    updateTopBar();
    await refreshSessions();
    await loadSessionMessages();
    await refreshFiles();
  });

  els.sessionSearch.addEventListener("input", () => renderSessionList());

  els.createSessionBtn.addEventListener("click", async () => {
    if (!state.userId) {
      toast(els.toastHost, "请先选择用户", { variant: "warn" });
      return;
    }
    let sessionId = (els.newSessionId.value || "").trim();
    if (!sessionId) {
      sessionId = `s_${new Date().toISOString().replaceAll(":", "").replaceAll("-", "").slice(0, 15)}`;
    }
    try {
      await createSession(state.userId, sessionId);
      els.newSessionId.value = "";
      await refreshSessions();
      state.sessionId = sessionId;
      renderSessionList();
      await loadSessionMessages();
      await refreshFiles();
      toast(els.toastHost, `已创建会话：${sessionId}`, { variant: "info" });
    } catch (e) {
      toast(els.toastHost, String(e?.message || e || "创建会话失败"), { variant: "warn" });
    }
  });

  els.chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = (els.chatInput.value || "").trim();
    if (!msg || !state.userId || !state.sessionId) return;
    els.chatInput.value = "";
    appendMessage(els.chatInner, "user", msg);
    setStatus(els.statusDot, els.statusText, "thinking");
    const data = await sendChat(state.userId, state.sessionId, msg);
    await loadSessionMessages();
    setStatus(els.statusDot, els.statusText, "idle");
    await handleReply(data.reply || "");
  });

  els.exportBtn.addEventListener("click", async () => {
    if (!state.userId || !state.sessionId) return;
    const md = buildMarkdownExport(state.messages || []);
    const fn = `chat_${state.userId}_${state.sessionId}.md`;
    downloadTextFile(fn, md);
    toast(els.toastHost, "已导出", { variant: "info" });
  });

  els.clearBtn.addEventListener("click", async () => {
    if (!state.userId || !state.sessionId) return;
    await clearSession(state.userId, state.sessionId);
    await loadSessionMessages();
    toast(els.toastHost, "已清空上下文", { variant: "info" });
  });

  els.refreshFilesBtn.addEventListener("click", async () => {
    await refreshFiles();
    toast(els.toastHost, "已刷新", { variant: "info" });
  });

  els.drawerCloseBtn.addEventListener("click", () => closeDrawer());
  els.drawerEditor.addEventListener("input", () => updateGutter(els.drawerEditor.value));
  els.drawerEditor.addEventListener("scroll", () => {
    els.drawerGutter.scrollTop = els.drawerEditor.scrollTop;
  });
  els.drawerSaveBtn.addEventListener("click", async () => {
    const opened = state.openedFile;
    if (!opened || !opened.editable) return;
    if (opened.kind === "memory") {
      await saveUserMemoryFile(state.userId, els.drawerEditor.value);
      toast(els.toastHost, "已保存", { variant: "info" });
    }
  });
}

async function boot() {
  bindEvents();
  updateClock();
  window.setInterval(updateClock, 1000);
  setStatus(els.statusDot, els.statusText, "idle");
  await refreshUsers();
  await refreshSessions();
  await loadSessionMessages();
  await refreshFiles();
}

boot().catch((err) => {
  appendMessage(els.chatInner, "assistant", String(err?.message || err));
});
