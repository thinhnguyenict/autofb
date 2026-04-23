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

    return [
        'ok' => true,
        'renewed_count' => $renewedCount,
        'total_config_pages' => count($updatedIds),
        'missing_page_ids' => $missingIds,
        'long_user_token_expires_in' => (int) ($exchange['data']['expires_in'] ?? 0),
    ];
}

// ─── Router ──────────────────────────────────────────────────────────────────

$action = $_GET['action'] ?? '';

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
        if (!file_exists(CONFIG_JSON)) {
            echo json_encode(['error' => 'config.json not found']);
            break;
        }
        $raw = file_get_contents(CONFIG_JSON);
        $cfg = json_decode($raw, true);
        if ($cfg === null) {
            echo json_encode(['error' => 'Invalid JSON in config.json']);
            break;
        }
        echo json_encode(['config' => $cfg]);
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
        $allowed = ['excel', 'pages'];
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

        echo json_encode([
            'status' => 'renewed',
            'renewed_count' => $result['renewed_count'],
            'total_config_pages' => $result['total_config_pages'],
            'missing_page_ids' => $result['missing_page_ids'],
            'long_user_token_expires_in' => $result['long_user_token_expires_in'],
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
