<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$banco = __DIR__ . '/../dados/saae.db';
if (!is_file($banco)) {
    http_response_code(503);
    echo json_encode(['sucesso' => false, 'mensagem' => 'Banco SQLite não encontrado'], JSON_UNESCAPED_UNICODE);
    exit;
}

$tabelas = [
    'estacao-heartbeat' => 'estacao_heartbeat',
    'bombacorrego' => 'bombacorrego',
    'estadorele' => 'estadorele',
    'nivelalta' => 'nivelalta',
    'nivelquadrada' => 'nivelquadrada',
    'sirene' => 'sirene',
    'statussirene' => 'statussirene'
];

try {
    $pdo = new PDO('sqlite:file:' . realpath($banco) . '?mode=ro', null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
    ]);

    $dados = [];
    foreach ($tabelas as $feed => $tabela) {
        // Os nomes das tabelas são constantes definidas neste arquivo.
        // O heartbeat do Córrego é identificado exclusivamente pelo valor 1.
        // Outros valores (ex.: 2, de outra estação) não alteram seu estado.
        $filtro = $feed === 'estacao-heartbeat' ? " WHERE TRIM(valor) = '1'" : '';
        $resultado = $pdo->query("SELECT id, valor, data_hora FROM {$tabela}{$filtro} ORDER BY id DESC LIMIT 1")->fetch();
        if ($resultado) {
            $dados[$feed] = [
                'id' => (int)$resultado['id'],
                'valor' => $resultado['valor'],
                'recebido_em' => $resultado['data_hora']
            ];
        }
    }

    $ultimoHeartbeat = $pdo->query("
        SELECT data_hora FROM estacao_heartbeat
        WHERE origem = 'MQTT' AND TRIM(valor) = '1'
        ORDER BY id DESC LIMIT 1
    ")->fetchColumn();

    // Reconstitui os estados em ordem temporal. Registros INICIALIZACAO
    // são observações recebidas na inicialização, não mudanças físicas confirmadas.
    $consulta = $pdo->query("
        SELECT valor, data_hora, origem, 'botao' AS equipamento, id FROM bombacorrego
        UNION ALL
        SELECT valor, data_hora, origem, 'rele' AS equipamento, id FROM estadorele
        ORDER BY data_hora ASC, equipamento ASC, id ASC
    ");

    $estadoBotao = null;
    $estadoRele = null;
    $inicioDivergencia = null;
    $inicioInferido = false;

    while ($evento = $consulta->fetch()) {
        if ($evento['equipamento'] === 'botao') {
            $estadoBotao = strtoupper(trim((string)$evento['valor']));
        } else {
            $estadoRele = strtolower(trim((string)$evento['valor']));
        }

        $divergente = $estadoBotao === 'HIGH' && $estadoRele === 'desligado';
        if ($divergente && $inicioDivergencia === null) {
            $inicioDivergencia = $evento['data_hora'];
            $inicioInferido = $evento['origem'] === 'INICIALIZACAO';
        } elseif (!$divergente) {
            $inicioDivergencia = null;
            $inicioInferido = false;
        }
    }

    $divergenciaAtiva = $estadoBotao === 'HIGH' && $estadoRele === 'desligado';
    $segundosDivergencia = 0;
    if ($divergenciaAtiva && $inicioDivergencia !== null) {
        $inicioTimestamp = strtotime((string)$inicioDivergencia);
        if ($inicioTimestamp !== false) {
            $segundosDivergencia = max(0, time() - $inicioTimestamp);
        }
    }

    $alertaBomba = [
        'divergencia' => $divergenciaAtiva,
        'inicio' => $inicioDivergencia,
        'inicio_inferido' => $inicioInferido,
        'segundos' => $segundosDivergencia,
        'limite_segundos' => 120,
        'critico' => $divergenciaAtiva && $segundosDivergencia > 120
    ];

    echo json_encode([
        'sucesso' => true,
        'feeds' => $dados,
        'comunicacao' => [
            'corrego' => [
                'ultimo_heartbeat' => $ultimoHeartbeat ?: null,
                'limite_segundos' => 180
            ]
        ],
        'alertas' => ['bomba_corrego' => $alertaBomba],
        'controle' => ['bomba_configurada' => (static function (): bool {
            $arquivo = __DIR__ . '/../config/comandos.php';
            if (!is_file($arquivo)) return false;
            $c = require $arquivo;
            return is_array($c) && !empty($c['usuario']) && !empty($c['chave']) &&
                $c['usuario'] !== 'PREENCHA_USUARIO' && $c['chave'] !== 'PREENCHA_CHAVE';
        })()]
    ], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);

} catch (Throwable $erro) {
    error_log('SAAE status.php: ' . $erro->getMessage());
    http_response_code(503);
    echo json_encode([
        'sucesso' => false,
        'mensagem' => 'Erro ao consultar o banco SQLite'
    ], JSON_UNESCAPED_UNICODE);
}
