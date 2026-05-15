import {
  clearSession,
  confirmChat,
  createSession,
  createKnowledgeBase,
  deleteKnowledgeBase,
  getConfigFile,
  getKnowledgeBase,
  getSessionMessages,
  getUserMemoryFile,
  listKnowledgeBases,
  listSessions,
  listUsers,
  saveUserMemoryFile,
  sendChat,
  updateKnowledgeBase,
} from "./api.js";
import { appendMessage, confirmDialog, permissionPrompt, renderMessages, setOptions, setStatus, toast } from "./ui.js";

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
  createKbBtn: document.getElementById("createKbBtn"),
  kbList: document.getElementById("kbList"),

  drawer: document.getElementById("drawer"),
  drawerPath: document.getElementById("drawerPath"),
  drawerEditor: document.getElementById("drawerEditor"),
  drawerGutter: document.getElementById("drawerGutter"),
  drawerCloseBtn: document.getElementById("drawerCloseBtn"),
  drawerSaveBtn: document.getElementById("drawerSaveBtn"),

  busyOverlay: document.getElementById("busyOverlay"),
  busyText: document.getElementById("busyText"),

  toastHost: document.getElementById("toastHost"),
};

const state = {
  userId: "",
  sessionId: "",
  sessions: [],
  messages: [],
  createdAt: "",
  openedFile: null,
  kbItems: [],
};

function nowClockText() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function updateClock() {
  els.topClock.textContent = nowClockText();
}

function setBusy(on, text = "处理中…") {
  if (!els.busyOverlay) return;
  els.busyText.textContent = String(text || "处理中…");
  els.busyOverlay.style.display = on ? "grid" : "none";
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
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

function openDrawer({ path, content, editable, kind, kbName }) {
  state.openedFile = { path, kind, editable: !!editable, kbName: kbName || "" };
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

function _sanitizeKbName(s) {
  const v = String(s || "").trim();
  if (!v) return "";
  if (v.includes("/") || v.includes("\\") || v.includes("..")) return "";
  return v;
}

async function openKbCreateModal() {
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "modal";

    const title = document.createElement("div");
    title.className = "modal-title";
    title.textContent = "创建知识库";

    const body = document.createElement("div");
    body.className = "modal-body";
    body.style.whiteSpace = "normal";

    const nameInput = document.createElement("input");
    nameInput.className = "input";
    nameInput.placeholder = "名称（kb_name）";

    const descInput = document.createElement("input");
    descInput.className = "input";
    descInput.placeholder = "描述（可选）";

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "input";
    fileInput.accept = ".txt,.md,.doc,.docx";

    const contentInput = document.createElement("textarea");
    contentInput.className = "input";
    contentInput.style.height = "160px";
    contentInput.style.resize = "vertical";
    contentInput.placeholder = "内容（可粘贴或上传文件自动填充）";

    fileInput.addEventListener("change", async () => {
      const f = fileInput.files?.[0];
      if (!f) return;
      const name = String(f.name || "").toLowerCase();
      if (name.endsWith(".docx")) {
        setBusy(true, "正在解析 DOCX…");
        try {
          const buf = await f.arrayBuffer();
          const payload = {
            filename: String(f.name || ""),
            data_base64: arrayBufferToBase64(buf),
          };
          const res = await fetch(`/api/users/${encodeURIComponent(state.userId)}/rag/extract-text`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await res.json();
          contentInput.value = String(data?.content || "");
          if (!data?.ok) {
            toast(els.toastHost, String(data?.error || "DOCX 解析失败"), { variant: "warn" });
          }
        } catch (e) {
          contentInput.value = "";
          toast(els.toastHost, String(e?.message || e || "DOCX 解析失败"), { variant: "warn" });
        } finally {
          setBusy(false);
        }
        return;
      }
      try {
        const text = await f.text();
        contentInput.value = text;
      } catch {
        contentInput.value = "";
      }
    });

    const stack = document.createElement("div");
    stack.style.display = "grid";
    stack.style.gap = "10px";
    stack.appendChild(nameInput);
    stack.appendChild(descInput);
    stack.appendChild(fileInput);
    stack.appendChild(contentInput);
    body.appendChild(stack);

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "modal-btn secondary";
    cancelBtn.textContent = "取消";

    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.className = "modal-btn primary";
    okBtn.textContent = "创建";

    const cleanup = (result) => {
      document.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
      resolve(result);
    };

    const onKeyDown = (e) => {
      if (e.key === "Escape") cleanup(null);
    };

    cancelBtn.addEventListener("click", () => cleanup(null));
    okBtn.addEventListener("click", () => {
      const kbName = _sanitizeKbName(nameInput.value);
      if (!kbName) {
        toast(els.toastHost, "知识库名称不合法", { variant: "warn" });
        return;
      }
      cleanup({
        kb_name: kbName,
        description: String(descInput.value || ""),
        content: String(contentInput.value || ""),
      });
    });
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) cleanup(null);
    });

    document.addEventListener("keydown", onKeyDown);
    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    modal.appendChild(title);
    modal.appendChild(body);
    modal.appendChild(actions);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    nameInput.focus();
  });
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

async function refreshKnowledgeBases() {
  if (!state.userId) {
    els.kbList.innerHTML = "";
    state.kbItems = [];
    return;
  }
  let data;
  try {
    data = await listKnowledgeBases(state.userId);
  } catch (e) {
    els.kbList.innerHTML = "";
    state.kbItems = [];
    toast(els.toastHost, String(e?.message || e || "知识库加载失败"), { variant: "warn" });
    return;
  }
  const items = data?.items || [];
  state.kbItems = items;
  els.kbList.innerHTML = "";
  for (const it of items) {
    const kbName = String(it.kb_name || "");
    const row = document.createElement("div");
    row.className = "file-item kb-row";

    const left = document.createElement("div");
    left.style.display = "grid";
    left.style.gap = "4px";

    const name = document.createElement("div");
    name.className = "file-name";
    name.textContent = kbName || "（未命名）";

    const desc = document.createElement("div");
    desc.className = "file-path";
    const d = String(it.description || "").trim();
    desc.textContent = d || "（无描述）";
    desc.title = d;

    left.appendChild(name);
    left.appendChild(desc);

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "kb-del";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!kbName) return;
      const ok = await confirmDialog(`确认删除知识库：${kbName} ?`, {
        title: "删除知识库",
        yesText: "删除",
        noText: "取消",
      });
      if (!ok) return;
      try {
        const resp = await deleteKnowledgeBase(state.userId, kbName);
        if (!resp?.ok) {
          toast(els.toastHost, String(resp?.error || "删除失败"), { variant: "warn" });
          return;
        }
        await refreshKnowledgeBases();
        toast(els.toastHost, `已删除：${kbName}`, { variant: "info" });
      } catch (err) {
        toast(els.toastHost, String(err?.message || err || "删除失败"), { variant: "warn" });
      }
    });

    row.appendChild(left);
    row.appendChild(delBtn);
    row.addEventListener("click", async () => {
      if (!kbName) return;
      const kb = await getKnowledgeBase(state.userId, kbName);
      openDrawer({
        kind: "kb",
        path: `KB: ${kbName}${kb.description ? " — " + kb.description : ""}`,
        content: kb.content || "",
        editable: true,
        kbName,
      });
    });
    els.kbList.appendChild(row);
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
    await refreshKnowledgeBases();
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

  els.createKbBtn.addEventListener("click", async () => {
    if (!state.userId) return;
    const payload = await openKbCreateModal();
    if (!payload) return;
    try {
      setBusy(true, "正在创建知识库…");
      const resp = await createKnowledgeBase(state.userId, payload);
      if (!resp?.ok) {
        toast(els.toastHost, String(resp?.error || "创建失败"), { variant: "warn" });
        return;
      }
      await refreshKnowledgeBases();
      toast(els.toastHost, `已创建知识库：${payload.kb_name}`, { variant: "info" });
    } catch (e) {
      toast(els.toastHost, String(e?.message || e || "创建失败"), { variant: "warn" });
    } finally {
      setBusy(false);
    }
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
    } else if (opened.kind === "kb") {
      const kbName = String(opened.kbName || "");
      if (!kbName) return;
      try {
        setBusy(true, "正在更新知识库…");
        await updateKnowledgeBase(state.userId, kbName, { content: els.drawerEditor.value });
        toast(els.toastHost, "已保存", { variant: "info" });
        await refreshKnowledgeBases();
      } finally {
        setBusy(false);
      }
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
  await refreshKnowledgeBases();
}

boot().catch((err) => {
  appendMessage(els.chatInner, "assistant", String(err?.message || err));
});
