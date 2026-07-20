const tokenKey = "autofb-session";
const $ = (id) => document.getElementById(id);
let activeWorkspace = "";

function token() {
  return localStorage.getItem(tokenKey);
}

function message(text = "") {
  $("message").textContent = text;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[char]);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token()) headers.Authorization = `Bearer ${token()}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(payload.detail);
  }
  return response.status === 204 ? null : response.json();
}

function selectedMediaIds() {
  return [...document.querySelectorAll("input[name='media_ids']:checked")].map((input) => input.value);
}

async function loadAuditLogs() {
  try {
    return await api(`/workspaces/${activeWorkspace}/audit-logs`);
  } catch {
    return [];
  }
}

async function loadPublishJobs() {
  try {
    return await api(`/workspaces/${activeWorkspace}/publish-jobs`);
  } catch {
    return [];
  }
}

async function refresh() {
  const me = await api("/me");
  $("who").textContent = me.display_name;
  const spaces = await api("/workspaces");
  $("workspaces").innerHTML = spaces.map((space) => `<option value="${space.id}">${escapeHtml(space.name)}</option>`).join("");
  activeWorkspace = $("workspaces").value;
  await refreshWorkspace();
}

async function refreshWorkspace() {
  if (!activeWorkspace) return;
  const [pages, posts, connections, notifications, media, members, auditLogs] = await Promise.all([
  const [pages, posts, connections, notifications, media, members, auditLogs, publishJobs] = await Promise.all([
    api(`/workspaces/${activeWorkspace}/facebook/pages`),
    api(`/workspaces/${activeWorkspace}/posts`),
    api(`/workspaces/${activeWorkspace}/facebook/connections`),
    api(`/workspaces/${activeWorkspace}/notifications`),
    api(`/workspaces/${activeWorkspace}/media`),
    api(`/workspaces/${activeWorkspace}/members`),
    loadAuditLogs(),
    loadPublishJobs(),
  ]);
  $("page").innerHTML = pages.map((page) => `<option value="${page.id}">${escapeHtml(page.name)}</option>`).join("");
  $("pages").textContent = pages.length ? `${pages.length} Fanpage đã kết nối` : "Chưa có Fanpage";
  $("connections").innerHTML = connections.map((connection) => `<p>${escapeHtml(connection.display_name)} — ${escapeHtml(connection.expires_at || "không rõ hạn")}</p>`).join("") || "<p>Chưa có kết nối.</p>";
  $("members").innerHTML = members.map((member) => `<p>${escapeHtml(member.display_name)} — ${escapeHtml(member.email)} — <b>${escapeHtml(member.role)}</b></p>`).join("");
  $("notifications").innerHTML = notifications.map((notification) => `<p>${notification.read_at ? "✓" : "●"} ${escapeHtml(notification.message)}</p>`).join("") || "<p>Không có thông báo.</p>";
  $("audit-logs").innerHTML = auditLogs.map((log) => `<p>${escapeHtml(log.action)} — ${escapeHtml(log.actor_name || "system")} — ${escapeHtml(log.created_at)}</p>`).join("") || "<p>Chỉ owner/admin thấy nhật ký.</p>";
  $("media-list").innerHTML = media.map((asset) => `<p>${escapeHtml(asset.filename)} (${escapeHtml(asset.content_type)})</p>`).join("") || "<p>Chưa có media.</p>";
  $("media-options").innerHTML = media.map((asset) => `<label><input type="checkbox" name="media_ids" value="${asset.id}"> ${escapeHtml(asset.filename)}</label>`).join("") || "<p>Tải media trước nếu muốn đính kèm ảnh vào bài.</p>";
  $("posts").innerHTML = posts.map((post) => `<p><b>${escapeHtml(post.status)}</b> — ${escapeHtml(post.body)} (${post.media_count || 0} media)</p>`).join("") || "<p>Chưa có bài viết.</p>";
  $("posts").innerHTML = posts.map((post) => {
    const cancel = ["scheduled", "queued"].includes(post.status) ? ` <button type="button" data-cancel-post="${post.id}">Hủy lịch</button>` : "";
    return `<p><b>${escapeHtml(post.status)}</b> — ${escapeHtml(post.body)} (${post.media_count || 0} media)${cancel}</p>`;
  }).join("") || "<p>Chưa có bài viết.</p>";
  $("publish-jobs").innerHTML = publishJobs.map((job) => `<p><b>${escapeHtml(job.status)}</b> — ${escapeHtml(job.page_name)} — ${escapeHtml(job.run_at)} — thử ${job.attempts}</p>`).join("") || "<p>Chưa có job publish.</p>";
}

$("login").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email: $("email").value, password: $("password").value }) });
    localStorage.setItem(tokenKey, data.access_token);
    $("auth").hidden = true;
    $("app").hidden = false;
    await refresh();
  } catch (error) {
    message(error.message);
  }
};

$("register").onclick = async () => {
  try {
    await api("/auth/register", { method: "POST", body: JSON.stringify({ email: $("email").value, password: $("password").value, display_name: $("email").value.split("@")[0] }) });
    message("Đã tạo tài khoản. Hãy đăng nhập.");
  } catch (error) {
    message(error.message);
  }
};

$("media").onsubmit = async (event) => {
  event.preventDefault();
  const file = $("media-file").files[0];
  if (!file) return;
  try {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/api/v1/workspaces/${activeWorkspace}/media`, { method: "POST", headers: { Authorization: `Bearer ${token()}` }, body: form });
    if (!response.ok) throw new Error((await response.json()).detail);
    $("media-file").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("logout").onclick = async () => {
  await api("/auth/logout", { method: "POST" });
  localStorage.removeItem(tokenKey);
  location.reload();
};

$("workspace").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("/workspaces", { method: "POST", body: JSON.stringify({ name: $("workspace-name").value }) });
    await refresh();
  } catch (error) {
    message(error.message);
  }
};

$("member").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api(`/workspaces/${activeWorkspace}/members`, {
      method: "PUT",
      body: JSON.stringify({ email: $("member-email").value, role: $("member-role").value }),
    });
    $("member-email").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("mark-read").onclick = async () => {
  try {
    await api(`/workspaces/${activeWorkspace}/notifications/read`, { method: "POST" });
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("posts").onclick = async (event) => {
  const postId = event.target.dataset.cancelPost;
  if (!postId) return;
  try {
    await api(`/workspaces/${activeWorkspace}/posts/${postId}/cancel`, { method: "POST" });
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("workspaces").onchange = async (event) => {
  activeWorkspace = event.target.value;
  await refreshWorkspace();
};

$("connect").onclick = async () => {
  try {
    location.href = (await api(`/workspaces/${activeWorkspace}/facebook/connect`, { method: "POST" })).authorization_url;
  } catch (error) {
    message(error.message);
  }
};

$("post").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const post = await api(`/workspaces/${activeWorkspace}/posts`, {
      method: "POST",
      body: JSON.stringify({ page_id: $("page").value, body: $("body").value, media_ids: selectedMediaIds() }),
    });
    const scheduled = new Date($("scheduled").value);
    await api(`/workspaces/${activeWorkspace}/posts/${post.id}/schedule`, {
      method: "POST",
      body: JSON.stringify({ scheduled_at: scheduled.toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }),
    });
    $("body").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

if (token()) {
  $("auth").hidden = true;
  $("app").hidden = false;
  refresh().catch(() => {
    localStorage.removeItem(tokenKey);
    location.reload();
  });
}
