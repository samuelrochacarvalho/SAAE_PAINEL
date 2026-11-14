<?php
// Executed before every PHP request by the launcher, including /api endpoints.
if (!function_exists('saae_exigir_autorizacao')) {
    function saae_exigir_autorizacao(): void {
        if (session_status() !== PHP_SESSION_ACTIVE) session_start();
        if (!empty($_SESSION['saae_local_autorizado'])) {
            $bootFile = dirname(__DIR__, 2) . '/saae_privado/boot.json';
            $boot = is_file($bootFile) ? json_decode((string) @file_get_contents($bootFile), true) : null;
            if (is_array($boot) && !empty($boot['id']) &&
                hash_equals((string)$boot['id'], (string)($_SESSION['saae_local_boot'] ?? ''))) return;
        }
        $arquivo = dirname(__DIR__, 2) . '/saae_privado/acesso_remoto.json';
        $dados = is_file($arquivo) ? json_decode((string) @file_get_contents($arquivo), true) : null;
        $exp = is_array($dados) ? strtotime((string)($dados['expira_em'] ?? '')) : false;
        if (is_array($dados) && $exp && time() < $exp
            && !empty($_SESSION['saae_acesso_validado'])
            && (int)($_SESSION['saae_acesso_expira'] ?? 0) === $exp
            && hash_equals((string)($_SESSION['saae_token_hash'] ?? ''),
                hash('sha256', (string)($dados['codigo'] ?? '') . '|' . (string)($dados['url'] ?? '')))
            && strtolower((string)($_SERVER['HTTP_HOST'] ?? '')) === strtolower((string)(parse_url((string)($dados['url'] ?? ''), PHP_URL_HOST) ?: ''))
        ) return;
        if (str_starts_with((string)($_SERVER['REQUEST_URI'] ?? ''), '/api/')) {
            http_response_code(403);
            header('Content-Type: application/json; charset=utf-8');
            header('Cache-Control: no-store');
            exit(json_encode(['sucesso'=>false, 'erro'=>'Sessão expirada ou não autorizada']));
        }
        header('Location: /index.php', true, 302);
        exit;
    }
}
// The entry page is public; everything else PHP is authenticated.
$rota = parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH);
if ($rota !== '/' && $rota !== '/index.php') {
    saae_exigir_autorizacao();
}
