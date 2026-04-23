<?php
/**
 * AutoFB Web Interface – API endpoint
 * All requests must be authenticated (session).
 */

require_once __DIR__ . '/auth.php';

header('Content-Type: application/json; charset=utf-8');

// Reject unauthenticated requests
if (!auth_is_logged_in()) {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized']);
    exit;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Return the script config for $key, or send a 400 error.
 */
function get_script(string $key): array
{
    $scripts = SCRIPTS;
    if (!array_key_exists($key, $scripts)) {
        http_response_code(400);
        echo json_encode(['error' => 'Unknown script']);
        exit;
    }
    return $scripts[$key];
}

/**
 * Read the PID stored in $pid_file.
 * Returns the integer PID if the process is alive, or 0 otherwise.
 */
function read_pid(string $pid_file): int
{
    if (!file_exists($pid_file)) {
        return 0;
    }
    $pid = (int) trim(file_get_contents($pid_file));
    if ($pid <= 0) {
        return 0;
    }
    // Check if the process is still alive
    if (posix_kill($pid, 0)) {
        return $pid;
    }
    // Stale PID file – remove it
    @unlink($pid_file);
    return 0;
}

/**
 * Start a script as a background process and record its PID.
 */
function start_script(array $script): array
{
    $logDir = dirname($script['log']);
    if (!is_dir($logDir)) {
        mkdir($logDir, 0755, true);
    }

    $logFp = fopen($script['log'], 'a');
    if ($logFp === false) {
        return ['status' => 'error', 'message' => 'Cannot open log file for writing'];
    }

    $descriptors = [
        0 => ['pipe', 'r'],  // stdin
        1 => $logFp,         // stdout → log file
        2 => $logFp,         // stderr → log file
    ];

    // Use explicit argument array – no shell interpretation, no injection risk
    $proc = proc_open(['python3', $script['script']], $descriptors, $pipes);
    fclose($logFp);

    if (!is_resource($proc)) {
        return ['status' => 'error', 'message' => 'Could not start process'];
    }

    // Close stdin so the process doesn't wait for input
    fclose($pipes[0]);

    $status = proc_get_status($proc);
    $pid    = $status['pid'] ?? 0;

    // Detach: we don't need the handle any more
    proc_close($proc);

    if ($pid > 0) {
        file_put_contents($script['pid'], $pid);
        return ['status' => 'started', 'pid' => $pid];
    }
    return ['status' => 'error', 'message' => 'Could not determine process PID'];
}

/**
 * Stop a running script.
 */
function stop_script(array $script): array
{
    $pid = read_pid($script['pid']);
    if ($pid <= 0) {
        return ['status' => 'not_running'];
    }

    // Send SIGTERM, then wait up to 5 s, then SIGKILL
    posix_kill($pid, SIGTERM);
    $waited = 0;
    while ($waited < 5 && posix_kill($pid, 0)) {
        usleep(500000);
        $waited += 0.5;
    }
    if (posix_kill($pid, 0)) {
        posix_kill($pid, SIGKILL);
    }

    @unlink($script['pid']);
    return ['status' => 'stopped', 'pid' => $pid];
}

/**
 * Perform a GET request and decode JSON response.
 */
function http_get_json(string $url, array $query): array
{
    $fullUrl = $url . '?' . http_build_query($query);

    if (function_exists('curl_init')) {
        $ch = curl_init($fullUrl);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_CONNECTTIMEOUT => 10,
        ]);
        $response = curl_exec($ch);
        $error = curl_error($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($response === false) {
            return ['ok' => false, 'error' => 'HTTP request failed: ' . $error];
        }
    } else {
        $context = stream_context_create([
            'http' => [
                'method' => 'GET',
                'timeout' => 30,
                'ignore_errors' => true,
            ],
        ]);
        $response = @file_get_contents($fullUrl, false, $context);
        $status = 0;
        if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s/', $http_response_header[0], $m)) {
            $status = (int) $m[1];
        }
        if ($response === false) {
            return ['ok' => false, 'error' => 'HTTP request failed'];
        }
    }

    $data = json_decode($response, true);
    if (!is_array($data)) {
        return ['ok' => false, 'error' => 'Invalid JSON response'];
    }
    if ($status >= 400 || isset($data['error'])) {
        $message = $data['error']['message'] ?? ('Facebook API error (HTTP ' . $status . ')');
        return ['ok' => false, 'error' => $message, 'data' => $data];
    }

    return ['ok' => true, 'data' => $data];
}

/**
 * Renew all configured page tokens from a short-lived user token.
 */
function renew_page_tokens(string $appId, string $appSecret, string $shortToken): array
{
    $exchange = http_get_json(
        'https://graph.facebook.com/v19.0/oauth/access_token',
        [
            'grant_type' => 'fb_exchange_token',
            'client_id' => $appId,
            'client_secret' => $appSecret,
            'fb_exchange_token' => $shortToken,
        ]
    );
    if (!$exchange['ok']) {
        return ['ok' => false, 'error' => 'Không thể đổi sang long-lived token: ' . $exchange['error']];
    }

    $longUserToken = $exchange['data']['access_token'] ?? '';
    if ($longUserToken === '') {
        return ['ok' => false, 'error' => 'Facebook không trả về access_token mới'];
    }

    $accounts = http_get_json(
        'https://graph.facebook.com/v19.0/me/accounts',
        [
            'fields' => 'id,name,access_token',
            'access_token' => $longUserToken,
        ]
    );
    if (!$accounts['ok']) {
        return ['ok' => false, 'error' => 'Không thể lấy danh sách page token: ' . $accounts['error']];
    }

    $pages = $accounts['data']['data'] ?? [];
    if (!is_array($pages) || count($pages) === 0) {
        return ['ok' => false, 'error' => 'Không có page nào trả về từ /me/accounts'];
    }

    if (!file_exists(CONFIG_JSON)) {
        return ['ok' => false, 'error' => 'config.json not found'];
    }
    $raw = file_get_contents(CONFIG_JSON);
    $cfg = json_decode($raw, true);
    if (!is_array($cfg)) {
        return ['ok' => false, 'error' => 'Invalid JSON in config.json'];
    }
    if (!isset($cfg['pages']) || !is_array($cfg['pages'])) {
        $cfg['pages'] = [];
    }

    $tokenMap = [];
    $nameMap = [];
    foreach ($pages as $page) {
        $pid = (string) ($page['id'] ?? '');
        $ptk = (string) ($page['access_token'] ?? '');
        $pname = (string) ($page['name'] ?? '');
        if ($pid !== '' && $ptk !== '') {
            $tokenMap[$pid] = $ptk;
            $nameMap[$pid] = $pname;
        }
    }
    if (count($tokenMap) === 0) {
        return ['ok' => false, 'error' => 'Không tìm thấy page token hợp lệ'];
    }

    $existingIds = $cfg['pages']['page_id'] ?? [];
    $existingNames = $cfg['pages']['page_name'] ?? [];
    $existingTokens = $cfg['pages']['access_token'] ?? [];
    if (!is_array($existingIds)) {
        $existingIds = [];
    }
    if (!is_array($existingNames)) {
        $existingNames = [];
    }
    if (!is_array($existingTokens)) {
        $existingTokens = [];
    }

    $updatedIds = [];
    $updatedNames = [];
    $updatedTokens = [];
    $renewedCount = 0;
    $missingIds = [];

    if (count($existingIds) > 0) {
        foreach ($existingIds as $i => $id) {
            $sid = (string) $id;
            $updatedIds[] = $sid;
            $updatedNames[] = (string) ($existingNames[$i] ?? ($nameMap[$sid] ?? ''));
            if ($sid !== '' && isset($tokenMap[$sid])) {
                $updatedTokens[] = $tokenMap[$sid];
                $renewedCount++;
            } else {
                $updatedTokens[] = (string) ($existingTokens[$i] ?? '');
                if ($sid !== '') {
                    $missingIds[] = $sid;
                }
            }
        }
    } else {
        foreach ($tokenMap as $pid => $token) {
            $updatedIds[] = $pid;
            $updatedNames[] = $nameMap[$pid] ?? '';
            $updatedTokens[] = $token;
            $renewedCount++;
        }
    }

    $cfg['pages']['page_id'] = $updatedIds;
    $cfg['pages']['page_name'] = $updatedNames;
    $cfg['pages']['access_token'] = $updatedTokens;

    $json = json_encode($cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false || file_put_contents(CONFIG_JSON, $json) === false) {
        return ['ok' => false, 'error' => 'Failed to write config.json'];
    }

    $expiresIn = (int) ($exchange['data']['expires_in'] ?? 0);
    $expiresAt = $expiresIn > 0 ? date('d/m/Y H:i', time() + $expiresIn) : null;

    return [
        'ok' => true,
        'renewed_count' => $renewedCount,
        'total_config_pages' => count($updatedIds),
        'missing_page_ids' => $missingIds,
        'long_user_token' => $longUserToken,
        'long_user_token_expires_in' => $expiresIn,
        'long_user_token_expires_at' => $expiresAt,
    ];
}

function read_config_json(): array
{
    if (!file_exists(CONFIG_JSON)) {
        return ['ok' => false, 'error' => 'config.json not found'];
    }
    $raw = file_get_contents(CONFIG_JSON);
    $cfg = json_decode($raw, true);
    if (!is_array($cfg)) {
        return ['ok' => false, 'error' => 'Invalid JSON in config.json'];
    }
    return ['ok' => true, 'config' => $cfg];
}

function write_config_json(array $cfg): bool
{
    $json = json_encode($cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    return $json !== false && file_put_contents(CONFIG_JSON, $json) !== false;
}

function normalize_token_renew(array $cfg): array
{
    $tokenRenew = $cfg['token_renew'] ?? [];
    if (!is_array($tokenRenew)) {
        $tokenRenew = [];
    }

    return [
        'app_id' => trim((string) ($tokenRenew['app_id'] ?? '')),
        'app_secret' => trim((string) ($tokenRenew['app_secret'] ?? '')),
        'short_token' => trim((string) ($tokenRenew['short_token'] ?? '')),
        'short_token_expires_at' => (int) ($tokenRenew['short_token_expires_at'] ?? 0),
        'long_user_token' => trim((string) ($tokenRenew['long_user_token'] ?? '')),
        'long_user_token_expires_at' => (int) ($tokenRenew['long_user_token_expires_at'] ?? 0),
        'auto_renew_enabled' => isset($tokenRenew['auto_renew_enabled']) ? (bool) $tokenRenew['auto_renew_enabled'] : true,
        'notify_email' => trim((string) ($tokenRenew['notify_email'] ?? '')),
        'last_renew_at' => trim((string) ($tokenRenew['last_renew_at'] ?? '')),
        'last_error' => trim((string) ($tokenRenew['last_error'] ?? '')),
        'last_error_at' => trim((string) ($tokenRenew['last_error_at'] ?? '')),
    ];
}

function get_token_expiry_from_debug(string $appId, string $appSecret, string $token): int
{
    $res = http_get_json(
        'https://graph.facebook.com/v19.0/debug_token',
        [
            'input_token' => $token,
            'access_token' => $appId . '|' . $appSecret,
        ]
    );
    if (!$res['ok']) {
        return 0;
    }
    $data = $res['data']['data'] ?? [];
    if (!is_array($data)) {
        return 0;
    }
    if (isset($data['is_valid']) && !$data['is_valid']) {
        return 0;
    }
    return (int) ($data['expires_at'] ?? 0);
}

function notify_renew_failure(string $toEmail, string $message): void
{
    if ($toEmail === '' || !filter_var($toEmail, FILTER_VALIDATE_EMAIL)) {
        return;
    }
    $subject = '[AutoFB] Token renew failed';
    $body = "AutoFB không thể tự động renew token.\n\nChi tiết:\n" . $message . "\n\nThời gian: " . date('Y-m-d H:i:s');
    @mail($toEmail, $subject, $body);
}

function should_send_failure_email(array $tokenRenew, string $newMessage): bool
{
    $prevMessage = trim((string) ($tokenRenew['last_error'] ?? ''));
    $prevAt = trim((string) ($tokenRenew['last_error_at'] ?? ''));
    if ($prevMessage !== $newMessage) {
        return true;
    }
    $ts = strtotime($prevAt);
    if ($ts === false) {
        return true;
    }
    return (time() - $ts) >= 3600;
}

function auto_renew_tokens_if_needed(): ?string
{
    $cfgRead = read_config_json();
    if (!$cfgRead['ok']) {
        return null;
    }
    $cfg = $cfgRead['config'];
    $tokenRenew = normalize_token_renew($cfg);

    if (!$tokenRenew['auto_renew_enabled']) {
        return null;
    }

    $longExpiresAt = (int) $tokenRenew['long_user_token_expires_at'];
    $now = time();
    $renewBeforeSeconds = 24 * 3600;
    if ($longExpiresAt > ($now + $renewBeforeSeconds)) {
        return null;
    }

    $appId = $tokenRenew['app_id'];
    $appSecret = $tokenRenew['app_secret'];
    $shortToken = $tokenRenew['short_token'];

    if ($appId === '' || $appSecret === '' || $shortToken === '') {
        $msg = 'Thiếu App ID/App Secret/Short-lived User Token để tự động renew.';
        $cfg['token_renew']['last_error'] = $msg;
        $cfg['token_renew']['last_error_at'] = date('c');
        write_config_json($cfg);
        if (should_send_failure_email($tokenRenew, $msg)) {
            notify_renew_failure($tokenRenew['notify_email'], $msg);
        }
        return $msg;
    }

    $shortExpiresAt = (int) $tokenRenew['short_token_expires_at'];
    if ($shortExpiresAt <= 0) {
        $shortExpiresAt = get_token_expiry_from_debug($appId, $appSecret, $shortToken);
    }
    if ($shortExpiresAt <= ($now + 300)) {
        $msg = 'Short-lived User Token đã hết hạn hoặc sắp hết hạn, không thể tự động renew.';
        $cfg['token_renew']['short_token_expires_at'] = $shortExpiresAt;
        $cfg['token_renew']['last_error'] = $msg;
        $cfg['token_renew']['last_error_at'] = date('c');
        write_config_json($cfg);
        if (should_send_failure_email($tokenRenew, $msg)) {
            notify_renew_failure($tokenRenew['notify_email'], $msg);
        }
        return $msg;
    }

    $result = renew_page_tokens($appId, $appSecret, $shortToken);
    if (!$result['ok']) {
        $msg = 'Auto renew thất bại: ' . $result['error'];
        $cfgRead = read_config_json();
        if ($cfgRead['ok']) {
            $cfg = $cfgRead['config'];
            $cfg['token_renew']['short_token_expires_at'] = $shortExpiresAt;
            $cfg['token_renew']['last_error'] = $msg;
            $cfg['token_renew']['last_error_at'] = date('c');
            write_config_json($cfg);
        }
        if (should_send_failure_email($tokenRenew, $msg)) {
            notify_renew_failure($tokenRenew['notify_email'], $msg);
        }
        return $msg;
    }

    $cfgRead = read_config_json();
    if ($cfgRead['ok']) {
        $cfg = $cfgRead['config'];
        $cfg['token_renew'] = normalize_token_renew($cfg);
        $cfg['token_renew']['app_id'] = $appId;
        $cfg['token_renew']['app_secret'] = $appSecret;
        $cfg['token_renew']['short_token'] = $shortToken;
        $cfg['token_renew']['short_token_expires_at'] = $shortExpiresAt;
        $cfg['token_renew']['long_user_token'] = (string) ($result['long_user_token'] ?? '');
        $cfg['token_renew']['long_user_token_expires_at'] = ($now + (int) ($result['long_user_token_expires_in'] ?? 0));
        $cfg['token_renew']['last_renew_at'] = date('c');
        $cfg['token_renew']['last_error'] = '';
        $cfg['token_renew']['last_error_at'] = '';
        write_config_json($cfg);
    }

    return 'Hệ thống đã tự động renew page token thành công.';
}

// ─── Router ──────────────────────────────────────────────────────────────────

$action = $_GET['action'] ?? '';
$autoRenewNotice = null;
if (in_array($action, ['status', 'get_config', 'start', 'restart'], true)) {
    $autoRenewNotice = auto_renew_tokens_if_needed();
}

switch ($action) {

    // ── GET status of all scripts ────────────────────────────────────────────
    case 'status':
        $result = [];
        foreach (SCRIPTS as $key => $script) {
            $pid = read_pid($script['pid']);
            $result[$key] = [
                'name'    => $script['name'],
                'running' => $pid > 0,
                'pid'     => $pid,
            ];
        }
        if ($autoRenewNotice !== null) {
            $result['_auto_renew_notice'] = $autoRenewNotice;
        }
        echo json_encode($result);
        break;

    // ── Start a script ───────────────────────────────────────────────────────
    case 'start':
        $key    = $_POST['script'] ?? '';
        $script = get_script($key);

        $existing = read_pid($script['pid']);
        if ($existing > 0) {
            echo json_encode(['status' => 'already_running', 'pid' => $existing]);
            break;
        }
        echo json_encode(start_script($script));
        break;

    // ── Stop a script ────────────────────────────────────────────────────────
    case 'stop':
        $key    = $_POST['script'] ?? '';
        $script = get_script($key);
        echo json_encode(stop_script($script));
        break;

    // ── Restart a script ─────────────────────────────────────────────────────
    case 'restart':
        $key    = $_POST['script'] ?? '';
        $script = get_script($key);
        stop_script($script);
        sleep(1);
        echo json_encode(start_script($script));
        break;

    // ── Tail log ─────────────────────────────────────────────────────────────
    case 'log':
        $key    = $_GET['script'] ?? '';
        $script = get_script($key);
        $logFile = $script['log'];

        if (!file_exists($logFile)) {
            echo json_encode(['lines' => '(Log file not found)']);
            break;
        }

        // Read last LOG_LINES lines efficiently
        $lines = [];
        $fp    = fopen($logFile, 'r');
        if ($fp) {
            fseek($fp, 0, SEEK_END);
            $pos     = ftell($fp);
            $buffer  = '';
            $lineCount = 0;

            while ($pos > 0 && $lineCount < LOG_LINES + 1) {
                $read    = min(4096, $pos);
                $pos    -= $read;
                fseek($fp, $pos);
                $chunk   = fread($fp, $read);
                $buffer  = $chunk . $buffer;
                // Count only the newly prepended chunk's newlines to avoid re-scanning
                $lineCount += substr_count($chunk, "\n");
            }
            fclose($fp);
            $all   = explode("\n", $buffer);
            $lines = array_slice($all, -LOG_LINES);
        }
        echo json_encode(['lines' => implode("\n", $lines)]);
        break;

    // ── Read config.json ─────────────────────────────────────────────────────
    case 'get_config':
        $cfgRead = read_config_json();
        if (!$cfgRead['ok']) {
            echo json_encode(['error' => $cfgRead['error']]);
            break;
        }
        $cfg = $cfgRead['config'];
        $cfg['token_renew'] = normalize_token_renew($cfg);
        echo json_encode(['config' => $cfg, 'auto_renew_notice' => $autoRenewNotice]);
        break;

    // ── Save config.json ─────────────────────────────────────────────────────
    case 'save_config':
        $body = file_get_contents('php://input');
        $data = json_decode($body, true);
        if ($data === null) {
            http_response_code(400);
            echo json_encode(['error' => 'Invalid JSON payload']);
            break;
        }

        // Only allow known top-level keys to avoid overwriting unexpected data
        $allowed = ['excel', 'pages', 'token_renew'];
        foreach (array_keys($data) as $k) {
            if (!in_array($k, $allowed, true)) {
                http_response_code(400);
                echo json_encode(['error' => "Disallowed key: $k"]);
                break 2;
            }
        }

        // Validate page arrays have equal lengths
        if (isset($data['pages'])) {
            $p = $data['pages'];
            $lengths = [];
            foreach (['access_token', 'page_id', 'page_name'] as $field) {
                if (isset($p[$field]) && is_array($p[$field])) {
                    $lengths[] = count($p[$field]);
                }
            }
            if (count(array_unique($lengths)) > 1) {
                http_response_code(400);
                echo json_encode(['error' => 'access_token, page_id and page_name arrays must have the same length']);
                break;
            }
        }

        if (isset($data['token_renew'])) {
            if (!is_array($data['token_renew'])) {
                http_response_code(400);
                echo json_encode(['error' => 'token_renew must be an object']);
                break;
            }
            $tr = $data['token_renew'];
            $data['token_renew'] = [
                'app_id' => trim((string) ($tr['app_id'] ?? '')),
                'app_secret' => trim((string) ($tr['app_secret'] ?? '')),
                'short_token' => trim((string) ($tr['short_token'] ?? '')),
                'short_token_expires_at' => (int) ($tr['short_token_expires_at'] ?? 0),
                'long_user_token' => trim((string) ($tr['long_user_token'] ?? '')),
                'long_user_token_expires_at' => (int) ($tr['long_user_token_expires_at'] ?? 0),
                'auto_renew_enabled' => isset($tr['auto_renew_enabled']) ? (bool) $tr['auto_renew_enabled'] : true,
                'notify_email' => trim((string) ($tr['notify_email'] ?? '')),
                'last_renew_at' => trim((string) ($tr['last_renew_at'] ?? '')),
                'last_error' => trim((string) ($tr['last_error'] ?? '')),
                'last_error_at' => trim((string) ($tr['last_error_at'] ?? '')),
            ];

            $email = $data['token_renew']['notify_email'];
            if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
                http_response_code(400);
                echo json_encode(['error' => 'notify_email is invalid']);
                break;
            }
        }

        $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if (file_put_contents(CONFIG_JSON, $json) === false) {
            http_response_code(500);
            echo json_encode(['error' => 'Failed to write config.json']);
            break;
        }
        echo json_encode(['status' => 'saved']);
        break;

    // ── Renew page tokens from short-lived token ─────────────────────────────
    case 'renew_tokens':
        $body = file_get_contents('php://input');
        $data = json_decode($body, true);
        if (!is_array($data)) {
            http_response_code(400);
            echo json_encode(['error' => 'Invalid JSON payload']);
            break;
        }

        $appId = trim((string) ($data['app_id'] ?? ''));
        $appSecret = trim((string) ($data['app_secret'] ?? ''));
        $shortToken = trim((string) ($data['short_token'] ?? ''));

        if ($appId === '' || $appSecret === '' || $shortToken === '') {
            http_response_code(400);
            echo json_encode(['error' => 'Missing required fields: app_id, app_secret, short_token']);
            break;
        }
        if (!preg_match('/^[0-9]+$/', $appId)) {
            http_response_code(400);
            echo json_encode(['error' => 'Invalid app_id format']);
            break;
        }

        $result = renew_page_tokens($appId, $appSecret, $shortToken);
        if (!$result['ok']) {
            http_response_code(400);
            echo json_encode(['error' => $result['error']]);
            break;
        }

        $cfgRead = read_config_json();
        if ($cfgRead['ok']) {
            $cfg = $cfgRead['config'];
            $tokenRenew = normalize_token_renew($cfg);
            $shortExpiresAt = get_token_expiry_from_debug($appId, $appSecret, $shortToken);
            $tokenRenew['app_id'] = $appId;
            $tokenRenew['app_secret'] = $appSecret;
            $tokenRenew['short_token'] = $shortToken;
            $tokenRenew['short_token_expires_at'] = $shortExpiresAt;
            $tokenRenew['long_user_token'] = (string) ($result['long_user_token'] ?? '');
            $tokenRenew['long_user_token_expires_at'] = time() + (int) ($result['long_user_token_expires_in'] ?? 0);
            $tokenRenew['last_renew_at'] = date('c');
            $tokenRenew['last_error'] = '';
            $tokenRenew['last_error_at'] = '';
            $cfg['token_renew'] = $tokenRenew;
            write_config_json($cfg);
        }

        echo json_encode([
            'status' => 'renewed',
            'renewed_count' => $result['renewed_count'],
            'total_config_pages' => $result['total_config_pages'],
            'missing_page_ids' => $result['missing_page_ids'],
            'long_user_token' => $result['long_user_token'],
            'long_user_token_expires_in' => $result['long_user_token_expires_in'],
            'long_user_token_expires_at' => $result['long_user_token_expires_at'],
        ]);
        break;

    // ── Logout ───────────────────────────────────────────────────────────────
    case 'logout':
        auth_logout();
        echo json_encode(['status' => 'logged_out']);
        break;

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Unknown action']);
}
