export async function listUsers() {
  const res = await fetch("/api/users");
  if (!res.ok) throw new Error("Failed to list users");
  return await res.json();
}

export async function listSessions(userId) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/sessions`);
  if (!res.ok) throw new Error("Failed to list sessions");
  return await res.json();
}

export async function createSession(userId, sessionId) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return await res.json();
}

export async function sendChat(userId, sessionId, message) {
  const url = `/api/sessions/${encodeURIComponent(sessionId)}/chat?user_id=${encodeURIComponent(userId)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error("Chat request failed");
  return await res.json();
}

export async function confirmChat(userId, sessionId, confirmed) {
  const url = `/api/sessions/${encodeURIComponent(sessionId)}/chat/confirm?user_id=${encodeURIComponent(userId)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: !!confirmed }),
  });
  if (!res.ok) throw new Error("Confirm request failed");
  return await res.json();
}

export async function resetAgent(userId, sessionId) {
  const url = `/api/sessions/${encodeURIComponent(sessionId)}/agent/reset?user_id=${encodeURIComponent(userId)}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error("Failed to reset agent");
  return await res.json();
}

export async function getSessionMessages(userId, sessionId) {
  const url = `/api/users/${encodeURIComponent(userId)}/sessions/${encodeURIComponent(sessionId)}/messages`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load messages");
  return await res.json();
}

export async function clearSession(userId, sessionId) {
  const url = `/api/users/${encodeURIComponent(userId)}/sessions/${encodeURIComponent(sessionId)}/clear`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error("Failed to clear session");
  return await res.json();
}

export async function getConfigFile() {
  const res = await fetch("/api/files/config");
  if (!res.ok) throw new Error("Failed to load config file");
  return await res.json();
}

export async function getUserMemoryFile(userId) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/files/memory`);
  if (!res.ok) throw new Error("Failed to load user memory file");
  return await res.json();
}

export async function saveUserMemoryFile(userId, content) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/files/memory`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: String(content ?? "") }),
  });
  if (!res.ok) throw new Error("Failed to save user memory file");
  return await res.json();
}

export async function listKnowledgeBases(userId) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/rag/kbs`);
  if (!res.ok) throw new Error("Failed to list knowledge bases");
  return await res.json();
}

export async function getKnowledgeBase(userId, kbName) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/rag/kbs/${encodeURIComponent(kbName)}`);
  if (!res.ok) throw new Error("Failed to load knowledge base");
  return await res.json();
}

export async function createKnowledgeBase(userId, payload) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/rag/kbs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error("Failed to create knowledge base");
  return await res.json();
}

export async function updateKnowledgeBase(userId, kbName, payload) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/rag/kbs/${encodeURIComponent(kbName)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error("Failed to update knowledge base");
  return await res.json();
}

export async function deleteKnowledgeBase(userId, kbName) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}/rag/kbs/${encodeURIComponent(kbName)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete knowledge base");
  return await res.json();
}

export async function checkCommand(command) {
  const res = await fetch(`/api/security/command/check?command=${encodeURIComponent(command)}`);
  if (!res.ok) throw new Error("Failed to check command");
  return await res.json();
}
