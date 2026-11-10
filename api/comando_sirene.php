<?php
declare(strict_types=1);
session_start();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
function resposta(int $codigo, string $mensagem, array $extras = []): never {
    http_response_code($codigo);
    echo json_encode(array_merge(['sucesso' => $codigo < 300, 'mensagem' => $mensagem], $extras), JSON_UNESCAPED_UNICODE);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') resposta(405, 'Use POST.');
// O projeto atual não possui autenticação de operador: limitar a interface ao PC local.
if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true)) resposta(403, 'Controle disponível apenas no computador local.');
$token = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '';
if (!is_string($token) || empty($_SESSION['csrf_bomba']) || !hash_equals($_SESSION['csrf_bomba'], $token)) resposta(403, 'Sessão inválida. Recarregue o painel.');
$origem = $_SERVER['HTTP_ORIGIN'] ?? '';
if ($origem !== '') {
    $hostOrigem = parse_url($origem, PHP_URL_HOST);
    $portaOrigem = parse_url($origem, PHP_URL_PORT);
    if (!in_array($hostOrigem, ['127.0.0.1', 'localhost'], true) || $portaOrigem !== 8090) resposta(403, 'Origem não autorizada.');
}
$entrada = json_decode(file_get_contents('php://input') ?: '', true);
$comando = is_array($entrada) ? ($entrada['comando'] ?? null) : null;
if (!in_array($comando, ['HIGH', 'LOW'], true)) resposta(422, 'Comando inválido.');
$arquivoConfig = __DIR__ . '/../config/comandos.php';
if (!is_file($arquivoConfig)) resposta(503, 'Configuração de acesso não encontrada.');
$config = require $arquivoConfig;
if (!is_array($config) || empty($config['usuario']) || empty($config['chave']) ||
    $config['usuario'] === 'PREENCHA_USUARIO' || $config['chave'] === 'PREENCHA_CHAVE') resposta(503, 'Configure o usuário e a chave em config/comandos.php.');
$usuario = (string)$config['usuario'];
$chave = (string)$config['chave'];
if (!preg_match('/^[A-Za-z0-9_-]+$/', $usuario)) resposta(422, 'Usuário Adafruit IO inválido.');
$banco = __DIR__ . '/../dados/saae.db';
if (!is_file($banco)) resposta(503, 'Banco SQLite indisponível.');
try {
    $pdo = new PDO('sqlite:file:' . realpath($banco) . '?mode=ro', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $rele = $pdo->query('SELECT id, valor FROM statussirene ORDER BY id DESC LIMIT 1')->fetch(PDO::FETCH_ASSOC);
    $botao = $pdo->query('SELECT valor FROM sirene ORDER BY id DESC LIMIT 1')->fetchColumn();
    // Não dispensar LOW apenas porque o relé já está Desligado:
    // LOW é necessário para redefinir bombacorrego após uma queda.
    $comandoAnterior = $pdo->query('SELECT id FROM sirene ORDER BY id DESC LIMIT 1')->fetchColumn();
    // Impede envios duplicados durante uma janela curta, inclusive entre abas.
    $lock = fopen(sys_get_temp_dir() . '/saae_sirene_comando.lock', 'c+');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) resposta(429, 'Outro comando está em processamento.');
    rewind($lock);
    $ultimo = (int)trim(stream_get_contents($lock));
    if ($ultimo > 0 && time() - $ultimo < 15) resposta(429, 'Aguarde 15 segundos entre comandos.', ['aguardar_segundos' => 15 - (time() - $ultimo)]);
    // REST Adafruit IO v2; somente HTTPS. O token fica exclusivamente no servidor.
    $url = 'https://io.adafruit.com/api/v2/' . rawurlencode($usuario) . '/feeds/sirene/data';
    $corpo = json_encode(['value' => $comando]);
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $corpo,
            CURLOPT_HTTPHEADER => ['X-AIO-Key: ' . $chave, 'Content-Type: application/json', 'Accept: application/json'],
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 4, CURLOPT_TIMEOUT => 8,
            CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2]);
        $retorno = curl_exec($ch);
        $codigo = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $erro = curl_error($ch);
        curl_close($ch);
        if ($retorno === false) resposta(502, 'Não foi possível alcançar o Adafruit IO: ' . $erro);
    } else {
        $ctx = stream_context_create(['http' => ['method' => 'POST', 'timeout' => 8, 'ignore_errors' => true,
            'header' => "X-AIO-Key: {$chave}\r\nContent-Type: application/json\r\nAccept: application/json\r\n",
            'content' => $corpo], 'ssl' => ['verify_peer' => true, 'verify_peer_name' => true]]);
        $retorno = @file_get_contents($url, false, $ctx);
        $cabecalho = $http_response_header[0] ?? '';
        preg_match('/HTTP\/\S+\s+(\d+)/', $cabecalho, $m);
        $codigo = (int)($m[1] ?? 0);
        if ($retorno === false) resposta(502, 'Falha de comunicação HTTPS com Adafruit IO.');
    }
    if ($codigo < 200 || $codigo >= 300) resposta(502, 'Adafruit IO recusou o comando (HTTP ' . $codigo . ').');
    ftruncate($lock, 0); rewind($lock); fwrite($lock, (string)time()); fflush($lock);
    resposta(200, 'Comando publicado. Aguardando estado do relé.', ['ja_confirmado' => false, 'rele_id_antes' => (int)($rele['id'] ?? 0), 'comando_id_antes' => (int)$comandoAnterior]);
} catch (Throwable $e) {
    error_log('SAAE comando_sirene: ' . $e->getMessage());
    resposta(503, 'Erro interno no processamento do comando.');
}
