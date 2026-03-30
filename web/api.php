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

    // ── Logout ───────────────────────────────────────────────────────────────
    case 'logout':
        auth_logout();
        echo json_encode(['status' => 'logged_out']);
        break;

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Unknown action']);
}
