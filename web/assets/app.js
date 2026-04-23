/* ── AutoFB Dashboard – Frontend JavaScript ─────────────────────────────── */

const API = 'api.php';
let autoRefreshTimer = null;

// ── Toast helper ──────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
    const colors = {
        success : 'bg-success text-white',
        danger  : 'bg-danger text-white',
        warning : 'bg-warning text-dark',
        info    : 'bg-info text-dark',
    };
    const id   = 'toast_' + Date.now();
    const html = `
        <div id="${id}" class="toast align-items-center ${colors[type] ?? colors.info} border-0" role="alert" aria-live="assertive">
            <div class="d-flex">
                <div class="toast-body">${msg}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>`;
    document.getElementById('toastContainer').insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    new bootstrap.Toast(el, { delay: 3500 }).show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}

// ── API helper ────────────────────────────────────────────────────────────────
async function apiCall(action, body = null, method = 'GET') {
    const opts = { method };
    if (body) {
        opts.body = body;
    }
    const url = `${API}?action=${action}`;
    const res  = await fetch(url, opts);
    if (res.status === 401) {
        window.location.href = 'login.php';
        return null;
    }
    return res.json();
}

// ── Process status ────────────────────────────────────────────────────────────
async function refreshStatus() {
    const data = await apiCall('status');
    if (!data) return;

    for (const [key, info] of Object.entries(data)) {
        const card  = document.querySelector(`.process-card[data-script="${key}"]`);
        if (!card) continue;

        const badge = card.querySelector('.status-badge');
        const pidEl = card.querySelector('.process-pid');

        if (info.running) {
            badge.className = 'badge status-badge running';
            badge.innerHTML = '<i class="bi bi-circle-fill me-1 small"></i>Đang chạy';
            pidEl.textContent = `PID: ${info.pid}`;
        } else {
            badge.className = 'badge status-badge stopped';
            badge.innerHTML = '<i class="bi bi-circle me-1 small"></i>Đã dừng';
            pidEl.textContent = '';
        }
    }
}

// ── Process control ───────────────────────────────────────────────────────────
async function scriptAction(action, scriptKey) {
    const form = new FormData();
    form.append('script', scriptKey);

    const msgs = {
        start   : 'Đang khởi động…',
        stop    : 'Đang dừng…',
        restart : 'Đang khởi động lại…',
    };
    showToast(msgs[action] ?? 'Đang xử lý…', 'info');

    const data = await apiCall(action, form, 'POST');
    if (!data) return;

    const script = document.querySelector(`.process-card[data-script="${scriptKey}"] .process-name`)?.textContent?.trim() ?? scriptKey;

    if (data.status === 'started')         showToast(`✅ ${script} đã khởi động (PID: ${data.pid})`, 'success');
    else if (data.status === 'stopped')    showToast(`🛑 ${script} đã dừng`, 'warning');
    else if (data.status === 'already_running') showToast(`ℹ️ ${script} đã đang chạy (PID: ${data.pid})`, 'info');
    else if (data.status === 'not_running') showToast(`ℹ️ ${script} không đang chạy`, 'info');
    else if (data.error)                   showToast(`❌ Lỗi: ${data.error}`, 'danger');
    else                                   showToast(`✅ ${action} thành công`, 'success');

    await refreshStatus();
}

// ── Config / Token management ─────────────────────────────────────────────────
let configData = null;

async function loadConfig() {
    const data = await apiCall('get_config');
    if (!data || data.error) {
        showToast('Không thể đọc config.json: ' + (data?.error ?? 'Unknown error'), 'danger');
        return;
    }
    configData = data.config;
    renderConfig();
}

function renderConfig() {
    if (!configData) return;

    // Excel paths
    document.getElementById('cfgExcelPath').value    = configData.excel?.path ?? '';
    document.getElementById('cfgCaptionFile').value  = configData.excel?.caption_file ?? '';
    document.getElementById('cfgActId').value        = configData.pages?.act_id ?? '';

    // Pages table
    const tbody = document.getElementById('pagesBody');
    tbody.innerHTML = '';

    const tokens  = configData.pages?.access_token ?? [];
    const pageIds = configData.pages?.page_id       ?? [];
    const names   = configData.pages?.page_name     ?? [];

    const len = Math.max(tokens.length, pageIds.length, names.length);
    for (let i = 0; i < len; i++) {
        addPageRow(i + 1, names[i] ?? '', pageIds[i] ?? '', tokens[i] ?? '');
    }
}

function addPageRow(idx, name = '', pageId = '', token = '') {
    const tbody = document.getElementById('pagesBody');
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td class="text-center text-muted small row-num">${idx}</td>
        <td><input type="text" class="form-control form-control-sm pg-name" value="${escHtml(name)}" placeholder="Tên trang"></td>
        <td><input type="text" class="form-control form-control-sm pg-id"   value="${escHtml(pageId)}" placeholder="Page ID"></td>
        <td><input type="text" class="form-control form-control-sm pg-token" value="${escHtml(token)}" placeholder="Access Token"></td>
        <td class="text-center">
            <button class="btn btn-sm btn-outline-danger btn-remove-row" title="Xoá hàng này">
                <i class="bi bi-trash"></i>
            </button>
        </td>`;
    tbody.appendChild(tr);
    renumberRows();
}

function renumberRows() {
    document.querySelectorAll('#pagesBody .row-num').forEach((el, i) => {
        el.textContent = i + 1;
    });
}

function escHtml(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function collectConfig() {
    const rows   = [...document.querySelectorAll('#pagesBody tr')];
    const tokens = rows.map(r => r.querySelector('.pg-token').value.trim());
    const ids    = rows.map(r => r.querySelector('.pg-id').value.trim());
    const names  = rows.map(r => r.querySelector('.pg-name').value.trim());

    return {
        excel: {
            path         : document.getElementById('cfgExcelPath').value.trim(),
            caption_file : document.getElementById('cfgCaptionFile').value.trim(),
        },
        pages: {
            access_token : tokens,
            page_id      : ids,
            page_name    : names,
            act_id       : document.getElementById('cfgActId').value.trim(),
        },
    };
}

async function saveConfig() {
    const payload = collectConfig();
    const res = await fetch(`${API}?action=save_config`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(payload),
    });
    if (res.status === 401) { window.location.href = 'login.php'; return; }
    const data = await res.json();
    if (data.status === 'saved') {
        showToast('✅ Đã lưu config.json thành công!', 'success');
        configData = payload;
    } else {
        showToast('❌ Lỗi khi lưu: ' + (data.error ?? 'Unknown'), 'danger');
    }
}

async function renewTokens() {
    const appId = document.getElementById('renewAppId').value.trim();
    const appSecret = document.getElementById('renewAppSecret').value.trim();
    const shortToken = document.getElementById('renewShortToken').value.trim();

    if (!appId || !appSecret || !shortToken) {
        showToast('Vui lòng nhập đủ App ID, App Secret và short token', 'warning');
        return;
    }

    const btn = document.getElementById('btnRenewTokens');
    btn.disabled = true;
    const oldHtml = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Renewing...';

    try {
        const res = await fetch(`${API}?action=renew_tokens`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                app_id: appId,
                app_secret: appSecret,
                short_token: shortToken,
            }),
        });
        if (res.status === 401) { window.location.href = 'login.php'; return; }
        const data = await res.json();
        if (data.status === 'renewed') {
            let msg = `✅ Renew thành công ${data.renewed_count}/${data.total_config_pages} token`;
            if (Array.isArray(data.missing_page_ids) && data.missing_page_ids.length > 0) {
                msg += `. Thiếu page_id: ${data.missing_page_ids.join(', ')}`;
            }
            showToast(msg, data.missing_page_ids?.length ? 'warning' : 'success');

            // Populate result box
            const resultBox = document.getElementById('renewResult');
            resultBox.classList.remove('d-none', 'alert-warning');
            resultBox.classList.add(data.missing_page_ids?.length ? 'alert-warning' : 'alert-success');

            let statsHtml = `Đã cập nhật <strong>${data.renewed_count}</strong> / ${data.total_config_pages} page token vào config.json.`;
            if (Array.isArray(data.missing_page_ids) && data.missing_page_ids.length > 0) {
                statsHtml += ` <span class="text-danger">Không tìm thấy token cho page_id: ${escHtml(data.missing_page_ids.join(', '))}</span>`;
            }
            document.getElementById('renewResultStats').innerHTML = statsHtml;

            const expiryEl = document.getElementById('renewResultExpiry');
            if (data.long_user_token_expires_at) {
                expiryEl.textContent = ` — hết hạn lúc ${data.long_user_token_expires_at}`;
            } else {
                expiryEl.textContent = '';
            }

            const tokenInput = document.getElementById('renewResultToken');
            tokenInput.value = data.long_user_token ?? '';

            await loadConfig();
        } else {
            showToast('❌ Renew thất bại: ' + (data.error ?? 'Unknown'), 'danger');
        }
    } catch (err) {
        showToast('❌ Renew thất bại: ' + err.message, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldHtml;
    }
}

// ── Log viewer ────────────────────────────────────────────────────────────────
async function loadLog(script) {
    const data = await apiCall(`log&script=${encodeURIComponent(script)}`);
    const box  = document.getElementById('logContent');
    if (!data) return;
    box.textContent = data.lines ?? '(Không có log)';
    box.scrollTop   = box.scrollHeight;
}

// ── Event listeners ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

    // Initial data load
    refreshStatus();
    setInterval(refreshStatus, 10000); // refresh status every 10 s

    loadConfig();

    // Process control buttons
    document.getElementById('processCards').addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-script]');
        if (!btn) return;
        const script = btn.dataset.script;
        if (btn.classList.contains('btn-start'))   scriptAction('start',   script);
        if (btn.classList.contains('btn-stop'))    scriptAction('stop',    script);
        if (btn.classList.contains('btn-restart')) scriptAction('restart', script);
        if (btn.classList.contains('btn-log')) {
            document.getElementById('logScriptSelect').value = script;
            loadLog(script);
            document.getElementById('logs').scrollIntoView({ behavior: 'smooth' });
        }
    });

    // Add page row
    document.getElementById('btnToggleRenew').addEventListener('click', () => {
        document.getElementById('renewCard').classList.toggle('d-none');
    });

    document.getElementById('btnRenewTokens').addEventListener('click', renewTokens);

    document.getElementById('btnCopyUserToken').addEventListener('click', () => {
        const val = document.getElementById('renewResultToken').value;
        if (!val) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(val).then(() => {
                showToast('✅ Đã sao chép long-lived user token!', 'success');
            }).catch(() => {
                showToast('⚠️ Không thể sao chép tự động — hãy bôi đen và copy thủ công', 'warning');
                document.getElementById('renewResultToken').select();
            });
        } else {
            showToast('⚠️ Trình duyệt không hỗ trợ copy tự động — hãy bôi đen và copy thủ công', 'warning');
            document.getElementById('renewResultToken').select();
        }
    });

    document.getElementById('btnAddPage').addEventListener('click', () => {
        const count = document.querySelectorAll('#pagesBody tr').length;
        addPageRow(count + 1);
    });

    // Remove page row
    document.getElementById('pagesBody').addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-remove-row');
        if (!btn) return;
        btn.closest('tr').remove();
        renumberRows();
    });

    // Save config
    document.getElementById('btnSaveConfig').addEventListener('click', saveConfig);

    // Log: manual refresh
    document.getElementById('btnRefreshLog').addEventListener('click', () => {
        loadLog(document.getElementById('logScriptSelect').value);
    });

    // Log: auto-refresh toggle
    document.getElementById('chkAutoRefresh').addEventListener('change', (e) => {
        if (e.target.checked) {
            const run = () => loadLog(document.getElementById('logScriptSelect').value);
            run();
            autoRefreshTimer = setInterval(run, 5000);
        } else {
            clearInterval(autoRefreshTimer);
            autoRefreshTimer = null;
        }
    });

    // Log: script selector change
    document.getElementById('logScriptSelect').addEventListener('change', () => {
        if (document.getElementById('chkAutoRefresh').checked) {
            clearInterval(autoRefreshTimer);
            const run = () => loadLog(document.getElementById('logScriptSelect').value);
            run();
            autoRefreshTimer = setInterval(run, 5000);
        }
    });

    // Logout
    document.getElementById('btnLogout').addEventListener('click', async () => {
        await apiCall('logout');
        window.location.href = 'login.php';
    });
});
