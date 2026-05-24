<?php
/**
 * AutoFB Web Interface - Configuration
 * Adjust the constants below to match your VPS setup.
 */

// Absolute path to the autofb application directory
define('APP_DIR', dirname(__DIR__));

// Path to config.json (tokens, page IDs, etc.)
define('CONFIG_JSON', APP_DIR . '/config.json');

// Bcrypt hash of the dashboard password.
// Generate a new hash in PHP with: echo password_hash('yourpassword', PASSWORD_BCRYPT);
// Default hash below corresponds to: admin123  — CHANGE BEFORE DEPLOYING!
define('APP_PASSWORD_HASH', getenv('APP_PASSWORD_HASH') ?: '$2y$10$haQO0yMEMI/iyavnU7ftleEYMWkCkugirLXhgbCfVG/1k4cEWiW06');

// Session name
define('SESSION_NAME', 'autofb_session');

// Available scripts with their metadata
define('SCRIPTS', [
    'create_fb_post' => [
        'name'   => 'FB Post (create_fb_post.py)',
        'script' => APP_DIR . '/create_fb_post.py',
        'log'    => APP_DIR . '/nohup.out',
        'pid'    => '/tmp/autofb_fb_post.pid',
    ],
    'create_ad_post' => [
        'name'   => 'Ad Post (create_ad_post.py)',
        'script' => APP_DIR . '/create_ad_post.py',
        'log'    => APP_DIR . '/create_ad_post.log',
        'pid'    => '/tmp/autofb_ad_post.pid',
    ],
    'reels_poster' => [
        'name'   => 'Reels Poster (reels_poster.py)',
        'script' => APP_DIR . '/reels_poster.py',
        'log'    => APP_DIR . '/reels_poster.log',
        'pid'    => '/tmp/autofb_reels.pid',
    ],
]);

// Maximum log lines to display in the UI
define('LOG_LINES', 200);
