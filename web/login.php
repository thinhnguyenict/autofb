<?php
require_once __DIR__ . '/auth.php';

if (auth_is_logged_in()) {
    header('Location: index.php');
    exit;
}

$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $password = $_POST['password'] ?? '';
    if (auth_login($password)) {
        header('Location: index.php');
        exit;
    }
    $error = 'Mật khẩu không đúng. Vui lòng thử lại.';
}
?>
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoFB – Đăng nhập</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
    <link rel="stylesheet" href="assets/style.css">
</head>
<body class="bg-dark d-flex align-items-center justify-content-center min-vh-100">
    <div class="card shadow-lg" style="width:360px">
        <div class="card-body p-4">
            <div class="text-center mb-4">
                <i class="bi bi-facebook fs-1 text-primary"></i>
                <h4 class="mt-2 fw-bold">AutoFB Dashboard</h4>
                <p class="text-muted small">Quản lý tự động đăng bài Facebook</p>
            </div>
            <?php if ($error): ?>
                <div class="alert alert-danger py-2 small"><?= htmlspecialchars($error) ?></div>
            <?php endif; ?>
            <form method="post">
                <div class="mb-3">
                    <label class="form-label fw-semibold">Mật khẩu</label>
                    <div class="input-group">
                        <span class="input-group-text"><i class="bi bi-lock"></i></span>
                        <input type="password" name="password" class="form-control"
                               placeholder="Nhập mật khẩu..." autofocus required>
                    </div>
                </div>
                <button type="submit" class="btn btn-primary w-100">
                    <i class="bi bi-box-arrow-in-right me-1"></i> Đăng nhập
                </button>
            </form>
        </div>
    </div>
</body>
</html>
