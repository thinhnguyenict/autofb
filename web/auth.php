<?php
/**
 * AutoFB Web Interface - Authentication helper
 */

require_once __DIR__ . '/config.php';

function auth_start_session(): void
{
    if (session_status() === PHP_SESSION_NONE) {
        session_name(SESSION_NAME);
        session_start();
    }
}

function auth_is_logged_in(): bool
{
    auth_start_session();
    return !empty($_SESSION['autofb_logged_in']);
}

function auth_require_login(): void
{
    if (!auth_is_logged_in()) {
        header('Location: login.php');
        exit;
    }
}

function auth_login(string $password): bool
{
    auth_start_session();
    if (password_verify($password, APP_PASSWORD_HASH)) {
        session_regenerate_id(true);
        $_SESSION['autofb_logged_in'] = true;
        return true;
    }
    return false;
}

function auth_logout(): void
{
    auth_start_session();
    $_SESSION = [];
    session_destroy();
}
