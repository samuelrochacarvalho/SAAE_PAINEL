<?php

declare(strict_types=1);
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_start();
}
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
function resposta(int $codigo, string $mensagem, array $extras = []): never
{
    http_response_code($codigo);
    echo json_encode(array_merge(['sucesso' => $codigo < 300, 'mensagem' => $mensagem], $extras), JSON_UNESCAPED_UNICODE);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') resposta(405, 'Use POST.');
// A autorização de sessão é exigida pelo auto_prepend_file (api/proteger_acesso.php).
// O Cloudflare encaminha a conexão ao PHP via loopback; REMOTE_ADDR não distingue
// acesso local de remoto. Por isso, a origem remota é validada contra o túnel ativo.
$token = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '';
if (!is_string($token) || empty($_SESSION['csrf_bomba']) || !hash_equals($_SESSION['csrf_bomba'], $token)) resposta(403, 'Sessão inválida. Recarregue o painel.');

$origem = (string)($_SERVER['HTTP_ORIGIN'] ?? '');
$hostRequisicao = strtolower((string)($_SERVER['HTTP_HOST'] ?? ''));
$origemLocal = 'http://127.0.0.1:8090';
$origemLocalAlternativa = 'http://localhost:8090';

// Aceita somente o domínio HTTPS do túnel atualmente registrado, ainda válido.
$arquivoRemoto = dirname(__DIR__, 2) . '/saae_privado/acesso_remoto.json';
$registroRemoto = is_file($arquivoRemoto)
    ? json_decode((string)@file_get_contents($arquivoRemoto), true)
    : null;
$origemRemota = '';
if (is_array($registroRemoto)) {
    $urlRegistrada = rtrim((string)($registroRemoto['url'] ?? ''), '/');
    $expiracao = strtotime((string)($registroRemoto['expira_em'] ?? ''));
    $partes = parse_url($urlRegistrada);
    if (
        $expiracao !== false && time() < $expiracao
        && is_array($partes)
        && strtolower((string)($partes['scheme'] ?? '')) === 'https'
        && preg_match('/^[a-z0-9-]+\.trycloudflare\.com$/i', (string)($partes['host'] ?? ''))
        && !isset($partes['port']) && !isset($partes['user']) && !isset($partes['pass'])
        && !isset($partes['path']) && !isset($partes['query']) && !isset($partes['fragment'])
    ) {
        $origemRemota = 'https://' . strtolower((string)$partes['host']);
    }
}

$origensPermitidas = [$origemLocal, $origemLocalAlternativa];
if ($origemRemota !== '') $origensPermitidas[] = $origemRemota;

// A origem e o host da requisição precisam corresponder ao mesmo endereço autorizado.
// Sem Origin, o CSRF permanece obrigatório e o Host ainda é validado.
$origemRequisicao = $origem !== '' ? rtrim($origem, '/') : '';
$enderecoRequisicao = $origemRequisicao !== '' ? $origemRequisicao : (
    $hostRequisicao === '127.0.0.1:8090' ? $origemLocal : (
        $hostRequisicao === 'localhost:8090' ? $origemLocalAlternativa : $origemRemota
    )
);
$hostEsperado = (string)parse_url($enderecoRequisicao, PHP_URL_HOST);
$portaEsperada = parse_url($enderecoRequisicao, PHP_URL_PORT);
$hostPortaEsperado = strtolower($hostEsperado . ($portaEsperada !== null ? ':' . $portaEsperada : ''));
if (
    !in_array($enderecoRequisicao, $origensPermitidas, true)
    || $hostRequisicao !== $hostPortaEsperado
) {
    resposta(403, 'Origem não autorizada.');
}
$entrada = json_decode(file_get_contents('php://input') ?: '', true);
$comando = is_array($entrada) ? ($entrada['comando'] ?? null) : null;
if (!in_array($comando, ['HIGH', 'LOW'], true)) resposta(422, 'Comando inválido.');
$arquivoConfig = __DIR__ . '/../config/comandos.php';
if (!is_file($arquivoConfig)) resposta(503, 'Configuração de acesso não encontrada.');
$config = require $arquivoConfig;
if (
    !is_array($config) || empty($config['usuario']) || empty($config['chave']) ||
    $config['usuario'] === 'PREENCHA_USUARIO' || $config['chave'] === 'PREENCHA_CHAVE'
) resposta(503, 'Configure o usuário e a chave em config/comandos.php.');
$usuario = (string)$config['usuario'];
$chave = (string)$config['chave'];
if (!preg_match('/^[A-Za-z0-9_-]+$/', $usuario)) resposta(422, 'Usuário Adafruit IO inválido.');
$banco = __DIR__ . '/../dados/saae.db';
if (!is_file($banco)) resposta(503, 'Banco SQLite indisponível.');
try {
    $pdo = new PDO('sqlite:file:' . realpath($banco) . '?mode=ro', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $rele = $pdo->query('SELECT id, valor FROM estadorele ORDER BY id DESC LIMIT 1')->fetch(PDO::FETCH_ASSOC);
    $botao = $pdo->query('SELECT valor FROM bombacorrego ORDER BY id DESC LIMIT 1')->fetchColumn();
    // Não dispensar LOW apenas porque o relé já está Desligado:
    // LOW é necessário para redefinir bombacorrego após uma queda.
    $comandoAnterior = $pdo->query('SELECT id FROM bombacorrego ORDER BY id DESC LIMIT 1')->fetchColumn();
    // Impede envios duplicados durante uma janela curta, inclusive entre abas.
    $lock = fopen(sys_get_temp_dir() . '/saae_bomba_comando.lock', 'c+');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) resposta(429, 'Outro comando está em processamento.');
    rewind($lock);
    $ultimo = (int)trim(stream_get_contents($lock));
    if ($ultimo > 0 && time() - $ultimo < 15) resposta(429, 'Aguarde 15 segundos entre comandos.', ['aguardar_segundos' => 15 - (time() - $ultimo)]);
    // REST Adafruit IO v2; somente HTTPS. O token fica exclusivamente no servidor.
    $url = 'https://io.adafruit.com/api/v2/' . rawurlencode($usuario) . '/feeds/bombacorrego/data';
    $corpo = json_encode(['value' => $comando]);
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $corpo,
            CURLOPT_HTTPHEADER => ['X-AIO-Key: ' . $chave, 'Content-Type: application/json', 'Accept: application/json'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 4,
            CURLOPT_TIMEOUT => 8,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2
        ]);
        $retorno = curl_exec($ch);
        $codigo = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $erro = curl_error($ch);
        curl_close($ch);
        if ($retorno === false) resposta(502, 'Não foi possível alcançar o Adafruit IO: ' . $erro);
    } else {
        $ctx = stream_context_create(['http' => [
            'method' => 'POST',
            'timeout' => 8,
            'ignore_errors' => true,
            'header' => "X-AIO-Key: {$chave}\r\nContent-Type: application/json\r\nAccept: application/json\r\n",
            'content' => $corpo
        ], 'ssl' => ['verify_peer' => true, 'verify_peer_name' => true]]);
        $retorno = @file_get_contents($url, false, $ctx);
        $cabecalho = $http_response_header[0] ?? '';
        preg_match('/HTTP\/\S+\s+(\d+)/', $cabecalho, $m);
        $codigo = (int)($m[1] ?? 0);
        if ($retorno === false) resposta(502, 'Falha de comunicação HTTPS com Adafruit IO.');
    }
    if ($codigo < 200 || $codigo >= 300) resposta(502, 'Adafruit IO recusou o comando (HTTP ' . $codigo . ').');
    ftruncate($lock, 0);
    rewind($lock);
    fwrite($lock, (string)time());
    fflush($lock);
    resposta(200, 'Comando publicado. Aguardando estado do relé.', ['ja_confirmado' => false, 'rele_id_antes' => (int)($rele['id'] ?? 0), 'comando_id_antes' => (int)$comandoAnterior]);
} catch (Throwable $e) {
    error_log('SAAE comando_bomba: ' . $e->getMessage());
    resposta(503, 'Erro interno no processamento do comando.');
}
