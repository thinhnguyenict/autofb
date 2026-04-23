<?php
require_once __DIR__ . '/auth.php';
auth_require_login();
$scripts = SCRIPTS;
?>
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoFB Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
    <link rel="stylesheet" href="assets/style.css">
</head>
<body class="bg-body-secondary">

<!-- ── Navbar ─────────────────────────────────────────────────────────────── -->
<nav class="navbar navbar-expand-lg navbar-dark bg-primary shadow-sm">
    <div class="container-fluid">
        <a class="navbar-brand fw-bold" href="#">
            <i class="bi bi-facebook me-1"></i> AutoFB Dashboard
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav ms-auto align-items-lg-center">
                <li class="nav-item">
                    <a class="nav-link" href="#processes"><i class="bi bi-cpu me-1"></i>Tiến trình</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#tokens"><i class="bi bi-key me-1"></i>Tokens</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="#logs"><i class="bi bi-journal-text me-1"></i>Logs</a>
                </li>
                <li class="nav-item ms-lg-2">
                    <button class="btn btn-sm btn-outline-light" id="btnLogout">
                        <i class="bi bi-box-arrow-right me-1"></i>Đăng xuất
                    </button>
                </li>
            </ul>
        </div>
    </div>
</nav>

<div class="container-fluid py-4 px-3 px-lg-4">

    <!-- ── Toast container ──────────────────────────────────────────────────── -->
    <div class="toast-container position-fixed bottom-0 end-0 p-3" style="z-index:9999" id="toastContainer"></div>

    <!-- ── Process status cards ─────────────────────────────────────────────── -->
    <section id="processes" class="mb-5">
        <h5 class="section-title mb-3">
            <i class="bi bi-cpu me-2 text-primary"></i>Quản lý tiến trình
        </h5>
        <div class="row g-3" id="processCards">
            <?php foreach ($scripts as $key => $script): ?>
            <div class="col-12 col-md-6 col-xl-4">
                <div class="card shadow-sm process-card" data-script="<?= htmlspecialchars($key) ?>">
                    <div class="card-body">
                        <div class="d-flex align-items-start justify-content-between mb-2">
                            <h6 class="card-title mb-0 fw-semibold process-name">
                                <?= htmlspecialchars($script['name']) ?>
                            </h6>
                            <span class="badge status-badge bg-secondary">
                                <i class="bi bi-circle-fill me-1 small"></i>Đang kiểm tra…
                            </span>
                        </div>
                        <p class="text-muted small mb-3 process-pid"></p>
                        <div class="d-flex gap-2 flex-wrap">
                            <button class="btn btn-sm btn-success btn-start" data-script="<?= htmlspecialchars($key) ?>">
                                <i class="bi bi-play-fill me-1"></i>Khởi động
                            </button>
                            <button class="btn btn-sm btn-warning btn-restart" data-script="<?= htmlspecialchars($key) ?>">
                                <i class="bi bi-arrow-clockwise me-1"></i>Khởi động lại
                            </button>
                            <button class="btn btn-sm btn-danger btn-stop" data-script="<?= htmlspecialchars($key) ?>">
                                <i class="bi bi-stop-fill me-1"></i>Dừng
                            </button>
                            <button class="btn btn-sm btn-outline-secondary btn-log ms-auto" data-script="<?= htmlspecialchars($key) ?>">
                                <i class="bi bi-journal-text me-1"></i>Xem log
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            <?php endforeach; ?>
        </div>
    </section>

    <!-- ── Token / config.json manager ─────────────────────────────────────── -->
    <section id="tokens" class="mb-5">
        <h5 class="section-title mb-3">
            <i class="bi bi-key me-2 text-primary"></i>Quản lý Tokens &amp; Trang (config.json)
        </h5>
        <div class="card shadow-sm">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                    <p class="text-muted small mb-0">
                        Mỗi hàng tương ứng một trang Facebook. Đảm bảo 3 cột có cùng số hàng.
                    </p>
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-outline-secondary" id="btnToggleRenew">
                            <i class="bi bi-arrow-repeat me-1"></i>Renew token
                        </button>
                        <button class="btn btn-sm btn-outline-primary" id="btnAddPage">
                            <i class="bi bi-plus-circle me-1"></i>Thêm trang
                        </button>
                        <button class="btn btn-sm btn-primary" id="btnSaveConfig">
                            <i class="bi bi-floppy me-1"></i>Lưu cấu hình
                        </button>
                    </div>
                </div>

                <!-- Token renew form -->
                <div class="card border-0 bg-body-tertiary mb-3 d-none" id="renewCard">
                    <div class="card-body py-3">
                        <div class="row g-2">
                            <div class="col-12 col-md-3">
                                <label class="form-label small fw-semibold">App ID</label>
                                <input type="text" class="form-control form-control-sm" id="renewAppId" placeholder="Ví dụ: 1234567890">
                            </div>
                            <div class="col-12 col-md-3">
                                <label class="form-label small fw-semibold">App Secret</label>
                                <input type="password" class="form-control form-control-sm" id="renewAppSecret" placeholder="App Secret">
                            </div>
                            <div class="col-12 col-md-5">
                                <label class="form-label small fw-semibold">Short-lived User Token</label>
                                <input type="password" class="form-control form-control-sm" id="renewShortToken" placeholder="Token từ Graph API Explorer">
                            </div>
                            <div class="col-12 col-md-1 d-grid align-self-end">
                                <button class="btn btn-sm btn-success" id="btnRenewTokens">
                                    <i class="bi bi-lightning-charge me-1"></i>Renew
                                </button>
                            </div>
                        </div>
                        <p class="text-muted small mt-2 mb-0">
                            Hệ thống sẽ tự động lấy page token mới và cập nhật trực tiếp vào <code>config.json</code> theo <code>page_id</code> hiện có.
                        </p>
                    </div>
                </div>

                <!-- Token renew result -->
                <div class="alert alert-success alert-dismissible d-none mb-3" id="renewResult" role="alert">
                    <div class="d-flex align-items-center mb-2">
                        <i class="bi bi-check-circle-fill me-2 fs-5"></i>
                        <strong id="renewResultTitle">Renew thành công</strong>
                        <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
                    </div>
                    <div class="mb-2 small" id="renewResultStats"></div>
                    <hr class="my-2">
                    <p class="small fw-semibold mb-1">
                        <i class="bi bi-key me-1"></i>Long-lived User Token
                        <span class="text-muted fw-normal" id="renewResultExpiry"></span>
                    </p>
                    <div class="input-group input-group-sm">
                        <input type="text" class="form-control font-monospace" id="renewResultToken" readonly>
                        <button class="btn btn-outline-secondary" id="btnCopyUserToken" title="Sao chép token">
                            <i class="bi bi-clipboard"></i>
                        </button>
                    </div>
                    <p class="text-muted small mt-2 mb-0">
                        <i class="bi bi-info-circle me-1"></i>
                        <strong>Page token</strong> đã lưu vào <code>config.json</code> là token vĩnh viễn (không hết hạn) và được dùng để đăng bài.
                        <strong>User token</strong> này hết hạn sau ~60 ngày — khi đó bạn cần lấy short token mới và renew lại.
                    </p>
                </div>

                <!-- Excel paths -->
                <div class="row g-3 mb-3">
                    <div class="col-12 col-md-6">
                        <label class="form-label small fw-semibold">Đường dẫn data.xlsx</label>
                        <input type="text" class="form-control form-control-sm" id="cfgExcelPath">
                    </div>
                    <div class="col-12 col-md-6">
                        <label class="form-label small fw-semibold">Đường dẫn caption.xlsx</label>
                        <input type="text" class="form-control form-control-sm" id="cfgCaptionFile">
                    </div>
                </div>

                <!-- act_id -->
                <div class="row g-3 mb-4">
                    <div class="col-12 col-md-6">
                        <label class="form-label small fw-semibold">Ad Account ID (act_id)</label>
                        <input type="text" class="form-control form-control-sm" id="cfgActId">
                    </div>
                </div>

                <!-- Pages table -->
                <div class="table-responsive">
                    <table class="table table-bordered table-sm align-middle" id="pagesTable">
                        <thead class="table-light">
                            <tr>
                                <th style="width:5%">#</th>
                                <th style="width:25%">Tên trang</th>
                                <th style="width:30%">Page ID</th>
                                <th>Access Token</th>
                                <th style="width:5%"></th>
                            </tr>
                        </thead>
                        <tbody id="pagesBody">
                            <!-- rows injected by JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </section>

    <!-- ── Log viewer ────────────────────────────────────────────────────────── -->
    <section id="logs" class="mb-5">
        <h5 class="section-title mb-3">
            <i class="bi bi-journal-text me-2 text-primary"></i>Xem Log
        </h5>
        <div class="card shadow-sm">
            <div class="card-body">
                <div class="d-flex gap-2 align-items-center mb-3 flex-wrap">
                    <select class="form-select form-select-sm" id="logScriptSelect" style="max-width:280px">
                        <?php foreach ($scripts as $key => $script): ?>
                        <option value="<?= htmlspecialchars($key) ?>"><?= htmlspecialchars($script['name']) ?></option>
                        <?php endforeach; ?>
                    </select>
                    <button class="btn btn-sm btn-outline-primary" id="btnRefreshLog">
                        <i class="bi bi-arrow-clockwise me-1"></i>Làm mới
                    </button>
                    <div class="form-check ms-auto">
                        <input class="form-check-input" type="checkbox" id="chkAutoRefresh">
                        <label class="form-check-label small" for="chkAutoRefresh">Tự động làm mới (5s)</label>
                    </div>
                </div>
                <pre id="logContent" class="log-box mb-0">Chọn tiến trình rồi nhấn "Làm mới" để xem log…</pre>
            </div>
        </div>
    </section>

</div><!-- /container -->

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="assets/app.js"></script>
</body>
</html>
