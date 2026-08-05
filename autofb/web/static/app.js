const tokenKey = "autofb-session";
const $ = (id) => document.getElementById(id);
let activeWorkspace = "";

function token() {
  return localStorage.getItem(tokenKey);
}

function message(text = "") {
  $("message").textContent = text;
}

function formatErrorDetail(detail) {
  if (Array.isArray(detail)) return detail.map((item) => formatErrorDetail(item)).join("; ");
  if (detail && typeof detail === "object") {
    const location = Array.isArray(detail.loc) ? detail.loc.join(".") : "";
    const prefix = location ? `${location}: ` : "";
    return `${prefix}${detail.msg || JSON.stringify(detail)}`;
  }
  return String(detail || "Request failed");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
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

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await fetch(`/api/v1${path}`, { ...options, headers, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Kết nối API quá lâu. Kiểm tra reverse proxy aaPanel tới http://127.0.0.1:8001.");
    }
    throw new Error(`Không gọi được API: ${error.message}`);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(formatErrorDetail(payload.detail));
  }
  return response.status === 204 ? null : response.json();
}

function selectedMediaIds() {
  return [...document.querySelectorAll("input[name='media_ids']:checked")].map((input) => input.value);
}

function postStatusQuery() {
  const status = $("post-status-filter").value;
  return status ? `?status_filter=${encodeURIComponent(status)}` : "";
}

function calendarRange() {
  const value = $("calendar-month").value;
  const [year, month] = value.split("-").map(Number);
  const start = new Date(Date.UTC(year, month - 1, 1));
  const end = new Date(Date.UTC(year, month, 1));
  return { dateFrom: start.toISOString(), dateTo: end.toISOString() };
}

async function fallbackList(path) {
  try {
    return await api(path);
  } catch {
    return [];
  }
}

async function fallbackObject(path, fallback) {
  try {
    return await api(path);
  } catch {
    return fallback;
  }
}

async function loadCalendar() {
  const { dateFrom, dateTo } = calendarRange();
  return fallbackList(`/workspaces/${activeWorkspace}/calendar?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`);
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
  const [pages, posts, connections, notifications, media, members, auditLogs, publishJobs, publishResults, publishMetrics, oauthStatus, summary, calendar] = await Promise.all([
    api(`/workspaces/${activeWorkspace}/facebook/pages`),
    api(`/workspaces/${activeWorkspace}/posts${postStatusQuery()}`),
    api(`/workspaces/${activeWorkspace}/facebook/connections`),
    api(`/workspaces/${activeWorkspace}/notifications`),
    api(`/workspaces/${activeWorkspace}/media`),
    api(`/workspaces/${activeWorkspace}/members`),
    fallbackList(`/workspaces/${activeWorkspace}/audit-logs`),
    fallbackList(`/workspaces/${activeWorkspace}/publish-jobs`),
    fallbackList(`/workspaces/${activeWorkspace}/publish-results`),
    fallbackObject(`/workspaces/${activeWorkspace}/publish-metrics`, null),
    fallbackObject(`/workspaces/${activeWorkspace}/facebook/oauth/status`, { configured: false, missing: ["status_unavailable"] }),
    fallbackObject(`/workspaces/${activeWorkspace}/summary`, null),
    loadCalendar(),
  ]);

  if (summary) {
    $("summary").innerHTML = `<p><b>Tổng quan:</b> ${summary.members} thành viên · ${summary.pages} Fanpage · ${summary.media} media · ${summary.posts} bài · ${summary.queued_jobs} job chờ · ${summary.unread_notifications} thông báo chưa đọc</p>`;
  } else {
    $("summary").textContent = "";
  }

  $("page").innerHTML = pages.map((page) => `<option value="${page.id}">${escapeHtml(page.name)}</option>`).join("");
  $("pages").innerHTML = pages.map((page) => `<p>${escapeHtml(page.name)} <small>${escapeHtml(page.facebook_page_id)}</small> <button type="button" data-delete-page="${page.id}">Xóa Fanpage</button></p>`).join("") || "<p>Chưa có Fanpage.</p>";
  $("oauth-status").innerHTML = oauthStatus.configured
    ? `<p>OAuth Facebook đã cấu hình. Redirect URI: ${escapeHtml(oauthStatus.redirect_uri || "")}</p>`
    : `<p>OAuth Facebook chưa sẵn sàng. Thiếu: ${escapeHtml((oauthStatus.missing || []).join(", "))}. Có thể dùng nhập Page token thủ công bên dưới.</p>`;

  const connectionHealth = { healthy: "còn hạn", expiring: "sắp hết hạn", expired: "đã hết hạn", unknown: "không rõ trạng thái" };
  $("connections").innerHTML = connections.map((connection) => `<p>${escapeHtml(connection.display_name)} — hạn: <b>${escapeHtml(connectionHealth[connection.health] || connection.health)}</b> — kiểm tra Meta: <b>${escapeHtml(connection.live_status || "chưa kiểm tra")}</b> ${connection.last_checked_at ? `(${escapeHtml(connection.last_checked_at)})` : ""} <button type="button" data-diagnose-connection="${connection.id}">Kiểm tra</button> <button type="button" data-delete-connection="${connection.id}">Gỡ kết nối</button></p>`).join("") || "<p>Chưa có kết nối.</p>";
  $("members").innerHTML = members.map((member) => {
    const remove = member.role !== "owner" ? ` <button type="button" data-remove-member="${member.id}">Xóa</button>` : "";
    return `<p>${escapeHtml(member.display_name)} — ${escapeHtml(member.email)} — <b>${escapeHtml(member.role)}</b>${remove}</p>`;
  }).join("");
  $("notifications").innerHTML = notifications.map((notification) => `<p>${notification.read_at ? "✓" : "●"} ${escapeHtml(notification.message)}</p>`).join("") || "<p>Không có thông báo.</p>";
  $("audit-logs").innerHTML = auditLogs.map((log) => `<p>${escapeHtml(log.action)} — ${escapeHtml(log.actor_name || "system")} — ${escapeHtml(log.created_at)}</p>`).join("") || "<p>Chỉ owner/admin thấy nhật ký.</p>";
  $("media-list").innerHTML = media.map((asset) => `<p>${escapeHtml(asset.filename)} (${escapeHtml(asset.content_type)}) <button type="button" data-delete-media="${asset.id}">Xóa</button></p>`).join("") || "<p>Chưa có media.</p>";
  $("media-options").innerHTML = media.map((asset) => `<label><input type="checkbox" name="media_ids" value="${asset.id}"> ${escapeHtml(asset.filename)}</label>`).join("") || "<p>Tải media trước nếu muốn đính kèm ảnh vào bài.</p>";

  $("posts").innerHTML = posts.map((post) => {
    const cancel = ["scheduled", "queued"].includes(post.status) ? ` <button type="button" data-cancel-post="${post.id}">Hủy lịch</button>` : "";
    const retry = post.status === "failed" ? ` <button type="button" data-retry-post="${post.id}">Thử lại</button>` : "";
    const editable = ["draft", "failed"].includes(post.status);
    const edit = editable ? ` <button type="button" data-edit-post="${post.id}" data-edit-body="${escapeHtml(post.body)}">Sửa</button>` : "";
    const duplicate = ` <button type="button" data-duplicate-post="${post.id}">Nhân bản</button>`;
    const remove = editable ? ` <button type="button" data-delete-post="${post.id}">Xóa bài</button>` : "";
    const requestApproval = editable && post.approval_status !== "pending" ? ` <button type="button" data-request-approval="${post.id}">Gửi duyệt</button>` : "";
    const reviewApproval = post.approval_status === "pending" ? ` <button type="button" data-approve-post="${post.id}">Duyệt</button> <button type="button" data-reject-post="${post.id}">Từ chối</button>` : "";
    const approval = post.approval_status ? ` · duyệt: <b>${escapeHtml(post.approval_status)}</b>` : "";
    return `<p><b>${escapeHtml(post.status)}</b>${approval} — ${escapeHtml(post.body)} (${post.media_count || 0} media)${cancel}${retry}${edit}${duplicate}${remove}${requestApproval}${reviewApproval}</p>`;
  }).join("") || "<p>Chưa có bài viết.</p>";

  $("calendar").innerHTML = calendar.map((post) => {
    const when = new Date(post.scheduled_at);
    return `<p><b>${escapeHtml(when.toLocaleString("vi-VN"))}</b> — ${escapeHtml(post.page_name)} — ${escapeHtml(post.body)} <small>${escapeHtml(post.status)}</small></p>`;
  }).join("") || "<p>Không có bài được lên lịch trong tháng này.</p>";
  $("publish-metrics").innerHTML = publishMetrics ? `<p><b>Metrics:</b> queued ${publishMetrics.jobs_queued} · running ${publishMetrics.jobs_running} · succeeded ${publishMetrics.jobs_succeeded} · failed ${publishMetrics.jobs_failed} · result OK ${publishMetrics.results_succeeded} · result lỗi ${publishMetrics.results_failed}</p>` : "";
  $("publish-jobs").innerHTML = publishJobs.map((job) => `<p><b>${escapeHtml(job.status)}</b> — ${escapeHtml(job.page_name)} — ${escapeHtml(job.run_at)} — thử ${job.attempts}</p>`).join("") || "<p>Chưa có job publish.</p>";
  $("publish-results").innerHTML = publishResults.map((result) => `<p><b>${escapeHtml(result.status)}</b> — ${escapeHtml(result.page_name)} — lần ${escapeHtml(result.attempt)} — ${escapeHtml(result.remote_post_id || result.error || result.created_at)}</p>`).join("") || "<p>Chưa có kết quả publish.</p>";
}

$("login").onsubmit = async (event) => {
  event.preventDefault();
  try {
    message("Đang đăng nhập...");
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
  if (!$("login").reportValidity()) return;
  try {
    message("Đang tạo tài khoản...");
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
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(formatErrorDetail(payload.detail));
    }
    $("media-file").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("rename-profile").onclick = async () => {
  const displayName = prompt("Tên hiển thị mới", $("who").textContent || "");
  if (displayName === null) return;
  try {
    const updated = await api("/me", { method: "PATCH", body: JSON.stringify({ display_name: displayName }) });
    $("who").textContent = updated.display_name;
    message("Đã đổi tên hiển thị.");
  } catch (error) {
    message(error.message);
  }
};

$("logout").onclick = async () => {
  await api("/auth/logout", { method: "POST" });
  localStorage.removeItem(tokenKey);
  location.reload();
};

$("password-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("/me/password", { method: "POST", body: JSON.stringify({ current_password: $("current-password").value, new_password: $("new-password").value }) });
    localStorage.removeItem(tokenKey);
    message("Đã đổi mật khẩu. Vui lòng đăng nhập lại.");
    setTimeout(() => location.reload(), 800);
  } catch (error) {
    message(error.message);
  }
};

$("workspace").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("/workspaces", { method: "POST", body: JSON.stringify({ name: $("workspace-name").value }) });
    $("workspace-name").value = "";
    await refresh();
  } catch (error) {
    message(error.message);
  }
};

$("rename-workspace").onclick = async () => {
  if (!activeWorkspace) return;
  const nextName = prompt("Tên workspace mới", $("workspaces").selectedOptions[0]?.textContent || "");
  if (nextName === null) return;
  try {
    await api(`/workspaces/${activeWorkspace}`, { method: "PATCH", body: JSON.stringify({ name: nextName }) });
    message("Đã đổi tên workspace.");
    await refresh();
  } catch (error) {
    message(error.message);
  }
};

$("delete-workspace").onclick = async () => {
  if (!activeWorkspace || !confirm("Xóa vĩnh viễn workspace cùng bài viết, lịch đăng, kết nối và media?")) return;
  try {
    await api(`/workspaces/${activeWorkspace}`, { method: "DELETE" });
    message("Đã xóa workspace.");
    await refresh();
  } catch (error) {
    message(error.message);
  }
};

$("delete-account").onclick = async () => {
  if (!confirm("Xóa tài khoản? Bạn phải xóa tất cả workspace đang sở hữu trước.")) return;
  const password = prompt("Nhập mật khẩu hiện tại để xác nhận");
  if (!password) return;
  try {
    await api("/me", { method: "DELETE", body: JSON.stringify({ password }) });
    localStorage.removeItem(tokenKey);
    location.reload();
  } catch (error) {
    message(error.message);
  }
};

$("member").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api(`/workspaces/${activeWorkspace}/members`, { method: "PUT", body: JSON.stringify({ email: $("member-email").value, role: $("member-role").value }) });
    $("member-email").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("members").onclick = async (event) => {
  const memberId = event.target.dataset.removeMember;
  if (!memberId) return;
  try {
    await api(`/workspaces/${activeWorkspace}/members/${memberId}`, { method: "DELETE" });
    message("Đã xóa thành viên khỏi workspace.");
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

$("clear-read").onclick = async () => {
  try {
    await api(`/workspaces/${activeWorkspace}/notifications/read`, { method: "DELETE" });
    message("Đã xóa thông báo đã đọc.");
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("pages").onclick = async (event) => {
  const pageId = event.target.dataset.deletePage;
  if (!pageId) return;
  try {
    await api(`/workspaces/${activeWorkspace}/facebook/pages/${pageId}`, { method: "DELETE" });
    message("Đã xóa Fanpage chưa dùng.");
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("connections").onclick = async (event) => {
  const connectionId = event.target.dataset.deleteConnection;
  const diagnoseId = event.target.dataset.diagnoseConnection;
  if (!connectionId && !diagnoseId) return;
  try {
    if (diagnoseId) {
      const result = await api(`/workspaces/${activeWorkspace}/facebook/connections/${diagnoseId}/diagnose`, { method: "POST" });
      message(result.valid ? "Kết nối Meta đang hoạt động." : `Kết nối Meta lỗi: ${result.detail || "token không hợp lệ"}`);
    } else {
      if (!confirm("Gỡ kết nối Facebook và các Fanpage chưa sử dụng?")) return;
      await api(`/workspaces/${activeWorkspace}/facebook/connections/${connectionId}`, { method: "DELETE" });
      message("Đã gỡ kết nối Facebook.");
    }
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("media-list").onclick = async (event) => {
  const mediaId = event.target.dataset.deleteMedia;
  if (!mediaId) return;
  try {
    await api(`/workspaces/${activeWorkspace}/media/${mediaId}`, { method: "DELETE" });
    message("Đã xóa media chưa dùng.");
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("posts").onclick = async (event) => {
  const postId = event.target.dataset.cancelPost;
  const retryPostId = event.target.dataset.retryPost;
  const deletePostId = event.target.dataset.deletePost;
  const editPostId = event.target.dataset.editPost;
  const duplicatePostId = event.target.dataset.duplicatePost;
  const requestApprovalId = event.target.dataset.requestApproval;
  const approvePostId = event.target.dataset.approvePost;
  const rejectPostId = event.target.dataset.rejectPost;
  if (!postId && !retryPostId && !deletePostId && !editPostId && !duplicatePostId && !requestApprovalId && !approvePostId && !rejectPostId) return;
  try {
    if (postId) {
      await api(`/workspaces/${activeWorkspace}/posts/${postId}/cancel`, { method: "POST" });
    } else if (retryPostId) {
      await api(`/workspaces/${activeWorkspace}/posts/${retryPostId}/retry`, { method: "POST" });
      message("Đã đưa bài viết lỗi vào hàng đợi thử lại.");
    } else if (deletePostId) {
      await api(`/workspaces/${activeWorkspace}/posts/${deletePostId}`, { method: "DELETE" });
      message("Đã xóa bài viết nháp/lỗi.");
    } else if (duplicatePostId) {
      await api(`/workspaces/${activeWorkspace}/posts/${duplicatePostId}/duplicate`, { method: "POST" });
      message("Đã nhân bản bài viết thành bản nháp mới.");
    } else if (requestApprovalId) {
      const comment = prompt("Ghi chú gửi duyệt (không bắt buộc)", "");
      if (comment === null) return;
      await api(`/workspaces/${activeWorkspace}/posts/${requestApprovalId}/approval`, { method: "POST", body: JSON.stringify({ comment: comment || null }) });
      message("Đã gửi bài viết để duyệt.");
    } else if (approvePostId || rejectPostId) {
      const decision = approvePostId ? "approved" : "rejected";
      const comment = prompt(decision === "approved" ? "Ghi chú phê duyệt" : "Lý do từ chối", "");
      if (comment === null) return;
      await api(`/workspaces/${activeWorkspace}/posts/${approvePostId || rejectPostId}/approval/review`, { method: "POST", body: JSON.stringify({ decision, comment: comment || null }) });
      message(decision === "approved" ? "Đã duyệt bài viết." : "Đã từ chối bài viết.");
    } else {
      const nextBody = prompt("Sửa nội dung bài viết", event.target.dataset.editBody || "");
      if (nextBody === null) return;
      await api(`/workspaces/${activeWorkspace}/posts/${editPostId}`, { method: "PATCH", body: JSON.stringify({ body: nextBody }) });
      message("Đã cập nhật bài viết.");
    }
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("workspaces").onchange = async (event) => {
  activeWorkspace = event.target.value;
  await refreshWorkspace();
};

$("post-status-filter").onchange = async () => {
  await refreshWorkspace();
};

$("calendar-month").onchange = async () => {
  await refreshWorkspace();
};

async function downloadFile(url, filename, successMessage) {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token()}` } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(formatErrorDetail(payload.detail));
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(objectUrl);
  message(successMessage);
}

$("export-posts").onclick = async () => {
  try {
    await downloadFile(`/api/v1/workspaces/${activeWorkspace}/posts/export${postStatusQuery()}`, `autofb-posts-${activeWorkspace}.csv`, "Đã xuất CSV bài viết.");
  } catch (error) {
    message(error.message);
  }
};

$("export-workspace").onclick = async () => {
  try {
    await downloadFile(`/api/v1/workspaces/${activeWorkspace}/export`, `autofb-workspace-${activeWorkspace}.json`, "Đã xuất dữ liệu workspace an toàn.");
  } catch (error) {
    message(error.message);
  }
};

$("connect").onclick = async () => {
  try {
    location.href = (await api(`/workspaces/${activeWorkspace}/facebook/connect`, { method: "POST" })).authorization_url;
  } catch (error) {
    message(error.message);
  }
};

$("manual-page").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api(`/workspaces/${activeWorkspace}/facebook/pages/manual`, {
      method: "POST",
      body: JSON.stringify({
        facebook_page_id: $("manual-page-id").value,
        name: $("manual-page-name").value,
        page_access_token: $("manual-page-token").value,
        expires_at: $("manual-page-expires").value || null,
      }),
    });
    $("manual-page").reset();
    message("Đã thêm Fanpage thủ công.");
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

async function createPostFromForm() {
  return api(`/workspaces/${activeWorkspace}/posts`, { method: "POST", body: JSON.stringify({ page_id: $("page").value, body: $("body").value, media_ids: selectedMediaIds() }) });
}

$("post").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const post = await createPostFromForm();
    const scheduled = new Date($("scheduled").value);
    await api(`/workspaces/${activeWorkspace}/posts/${post.id}/schedule`, { method: "POST", body: JSON.stringify({ scheduled_at: scheduled.toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }) });
    $("body").value = "";
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

$("publish-now").onclick = async () => {
  if (!$("page").value || !$("body").value.trim()) {
    message("Chọn Fanpage và nhập nội dung bài viết trước khi đăng ngay.");
    return;
  }
  try {
    const post = await createPostFromForm();
    await api(`/workspaces/${activeWorkspace}/posts/${post.id}/publish-now`, { method: "POST" });
    $("body").value = "";
    $("scheduled").value = "";
    message("Đã đưa bài viết vào hàng đợi đăng ngay.");
    await refreshWorkspace();
  } catch (error) {
    message(error.message);
  }
};

const calendarNow = new Date();
$("calendar-month").value = `${calendarNow.getFullYear()}-${String(calendarNow.getMonth() + 1).padStart(2, "0")}`;

if (token()) {
  $("auth").hidden = true;
  $("app").hidden = false;
  refresh().catch(() => {
    localStorage.removeItem(tokenKey);
    location.reload();
  });
}
