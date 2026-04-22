export function setOptions(selectEl, options, getLabel = (v) => String(v), getValue = (v) => String(v)) {
  selectEl.innerHTML = "";
  for (const opt of options) {
    const el = document.createElement("option");
    el.value = getValue(opt);
    el.textContent = getLabel(opt);
    selectEl.appendChild(el);
  }
}

export function appendMessage(chatLogEl, role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  chatLogEl.appendChild(div);
  const scroller = chatLogEl.closest?.(".chat-history") || chatLogEl;
  scroller.scrollTop = scroller.scrollHeight;
}

export function clearChat(chatLogEl) {
  chatLogEl.innerHTML = "";
}

export function renderMessages(chatLogEl, messages) {
  clearChat(chatLogEl);
  for (const m of messages || []) {
    const role = String(m?.role || "");
    if (!role) continue;
    const content = String(m?.content || "");
    appendMessage(chatLogEl, role, content);
  }
}

export function setStatus(dotEl, textEl, status) {
  const s = String(status || "idle");
  dotEl.classList.remove("idle", "thinking", "tool");
  dotEl.classList.add(s);
  if (s === "thinking") textEl.textContent = "思考中";
  else if (s === "tool") textEl.textContent = "执行工具";
  else textEl.textContent = "空闲";
}

export function toast(hostEl, message, { variant = "info", timeoutMs = 2800 } = {}) {
  const t = document.createElement("div");
  t.className = `toast ${variant}`;
  t.textContent = String(message || "");
  hostEl.appendChild(t);
  const remove = () => t.remove();
  window.setTimeout(remove, timeoutMs);
  return remove;
}

export function permissionPrompt(hostEl, { title, body, yesText = "确认", noText = "取消" }) {
  return new Promise((resolve) => {
    const card = document.createElement("div");
    card.className = "confirm-card";

    const h = document.createElement("div");
    h.className = "confirm-title";
    h.textContent = String(title || "需要确认");

    const b = document.createElement("div");
    b.className = "confirm-body";
    b.textContent = String(body || "");

    const actions = document.createElement("div");
    actions.className = "confirm-actions";

    const noBtn = document.createElement("button");
    noBtn.type = "button";
    noBtn.className = "btn secondary";
    noBtn.textContent = noText;

    const yesBtn = document.createElement("button");
    yesBtn.type = "button";
    yesBtn.className = "btn primary";
    yesBtn.textContent = yesText;

    const cleanup = (v) => {
      card.remove();
      resolve(v);
    };

    noBtn.addEventListener("click", () => cleanup(false));
    yesBtn.addEventListener("click", () => cleanup(true));

    actions.appendChild(noBtn);
    actions.appendChild(yesBtn);
    card.appendChild(h);
    card.appendChild(b);
    card.appendChild(actions);
    hostEl.appendChild(card);
    yesBtn.focus();
  });
}

export function confirmDialog(message, { title = "需要确认", yesText = "Yes", noText = "No" } = {}) {
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "modal";

    const h = document.createElement("div");
    h.className = "modal-title";
    h.textContent = title;

    const body = document.createElement("div");
    body.className = "modal-body";
    body.textContent = message;

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const noBtn = document.createElement("button");
    noBtn.type = "button";
    noBtn.className = "modal-btn secondary";
    noBtn.textContent = noText;

    const yesBtn = document.createElement("button");
    yesBtn.type = "button";
    yesBtn.className = "modal-btn primary";
    yesBtn.textContent = yesText;

    const cleanup = (result) => {
      document.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
      resolve(result);
    };

    const onKeyDown = (e) => {
      if (e.key === "Escape") cleanup(false);
    };

    document.addEventListener("keydown", onKeyDown);
    noBtn.addEventListener("click", () => cleanup(false));
    yesBtn.addEventListener("click", () => cleanup(true));
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) cleanup(false);
    });

    actions.appendChild(noBtn);
    actions.appendChild(yesBtn);
    modal.appendChild(h);
    modal.appendChild(body);
    modal.appendChild(actions);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    yesBtn.focus();
  });
}
