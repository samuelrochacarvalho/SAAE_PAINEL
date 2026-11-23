<?php

declare(strict_types=1);
require_once __DIR__ . '/api/proteger_acesso.php';
if (session_status() !== PHP_SESSION_ACTIVE) session_start();

$arquivo = dirname(__DIR__) . '/saae_privado/acesso_remoto.json';
$loginLocal = dirname(__DIR__) . '/saae_privado/login_local.json';
$bootFile = dirname(__DIR__) . '/saae_privado/boot.json';
$mensagem = '';
$sucesso = false;
$urlRedirecionamento = '';

// Local embedded WebView uses a one-time secret and its own PHP session.
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['segredo_local'])) {
    $segredo = (string) $_POST['segredo_local'];
    $registro = is_file($loginLocal) ? json_decode((string) file_get_contents($loginLocal), true) : null;
    if (strlen($segredo) >= 48 && is_array($registro) &&
        hash_equals((string) ($registro['hash'] ?? ''), hash('sha256', $segredo))) {
        session_regenerate_id(true);
        $_SESSION['saae_local_autorizado'] = true;
        $boot = json_decode((string) @file_get_contents($bootFile), true);
        $_SESSION['saae_local_boot'] = (string)($boot['id'] ?? '');
        @unlink($loginLocal);
        header('Location: /dashboard.php', true, 303);
        exit;
    }
    http_response_code(403);
    exit('Credencial local invalida. Reinicie o aplicativo.');
}

if (isset($_GET['local']) && $_GET['local'] === '1') {
    // This page only requests the bridge secret. It does not contain the secret.
    header('Cache-Control: no-store');
    ?>
    <!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Iniciando SAAE</title></head>
    <body style="background:#0b1220;color:white;font-family:Arial;text-align:center;padding-top:20vh">
    <h2>Autenticando aplicativo local...</h2><p id="estado">Aguarde.</p>
    <form id="entrada" method="post" action="/index.php">
      <input type="hidden" name="segredo_local" id="segredo_local">
    </form>
    <script>
      async function autenticar() {
        try {
          const segredo = await window.pywebview.api.autorizar_local();
          document.getElementById('segredo_local').value = segredo;
          document.getElementById('entrada').submit();
        } catch (e) {
          document.getElementById('estado').textContent = 'Falha na autenticação local: ' + e.message;
        }
      }
      if (window.pywebview?.api) autenticar();
      else window.addEventListener('pywebviewready', autenticar, {once:true});
    </script></body></html>
    <?php
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $codigo = trim((string) ($_POST['codigo'] ?? ''));
    if (!preg_match('/^\d{6}$/', $codigo)) {
        $mensagem = 'Informe um código válido de 6 dígitos.';
    } elseif (!is_file($arquivo)) {
        $mensagem = 'Nenhum acesso remoto foi gerado.';
    } else {
        $dados = json_decode((string) file_get_contents($arquivo), true);
        if (!is_array($dados)) {
            $mensagem = 'Registro de acesso inválido.';
        } else {
            $codigoSalvo = (string) ($dados['codigo'] ?? '');
            $expiracao = strtotime((string) ($dados['expira_em'] ?? ''));
            $url = (string) ($dados['url'] ?? '');
            $host = parse_url($url, PHP_URL_HOST);
            $hostRequisicao = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));
            if (!$expiracao || time() >= $expiracao) {
                $mensagem = 'Código expirado. Gere um novo acesso.';
            } elseif (!is_string($host) || !preg_match('/^[a-z0-9-]+\.trycloudflare\.com$/i', $host)
                || parse_url($url, PHP_URL_SCHEME) !== 'https' || $hostRequisicao !== strtolower($host)) {
                $mensagem = 'Endereço temporário inválido.';
            } elseif (!hash_equals($codigoSalvo, $codigo)) {
                $mensagem = 'Código inválido.';
            } else {
                session_regenerate_id(true);
                $_SESSION['saae_acesso_validado'] = true;
                $_SESSION['saae_acesso_expira'] = $expiracao;
                $_SESSION['saae_token_hash'] = hash('sha256', $codigoSalvo . '|' . $url);
                $sucesso = true;
                $mensagem = 'Código validado com sucesso!';
                $urlRedirecionamento = rtrim($url, '/') . '/dashboard.php';
            }
        }
    }
}
?>

<!DOCTYPE html>
<html lang="pt-BR">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SAAE | Validar Acesso</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #0b1220;
            color: #e8f0fa;
            font-family: Arial, sans-serif;
        }

        .card {
            width: min(400px, 92vw);
            background: #111c30;
            border: 1px solid #26384e;
            border-radius: 16px;
            padding: 30px;
            text-align: center;
        }

        h2 {
            margin: 0 0 12px;
        }

        p {
            color: #94a3b8;
            font-size: 14px;
        }

        input {
            width: 100%;
            padding: 15px;
            margin: 18px 0;
            background: #1e293b;
            border: 1px solid #475569;
            border-radius: 8px;
            color: #fff;
            font-size: 26px;
            letter-spacing: 6px;
            text-align: center;
        }

        button {
            width: 100%;
            padding: 13px;
            border: 0;
            border-radius: 8px;
            background: #0284c7;
            color: white;
            font-size: 15px;
            cursor: pointer;
        }

        .mensagem {
            margin-top: 15px;
            color: #fbbf24;
        }

        .sucesso {
            color: #4ade80;
        }
    </style>
</head>

<body>
    <div class="card">
        <h2>SAAE | Acesso Remoto</h2>
        <p>Digite o código de 6 dígitos exibido no painel.</p>

        <?php if ($sucesso): ?>

            <p class="mensagem sucesso">
                Código validado com sucesso!
            </p>

            <p>
                Você será redirecionado para o painel em
                <strong id="contador">5</strong> segundos.
            </p>

            <script>
                const urlDestino = <?= json_encode(
                                        $urlRedirecionamento,
                                        JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT
                                    ) ?>;

                let segundos = 5;

                const intervalo = setInterval(() => {
                    segundos--;

                    document.getElementById('contador').textContent =
                        segundos;

                    if (segundos <= 0) {
                        clearInterval(intervalo);
                        window.location.replace(urlDestino);
                    }
                }, 1000);
            </script>

        <?php else: ?>
            <form method="POST">
                <input
                    type="text"
                    name="codigo"
                    maxlength="6"
                    inputmode="numeric"
                    pattern="[0-9]{6}"
                    autocomplete="off"
                    placeholder="000000"
                    required>

                <button type="submit">
                    Validar acesso
                </button>
            </form>

            <?php if ($mensagem !== ''): ?>
                <p class="mensagem">
                    <?= htmlspecialchars($mensagem, ENT_QUOTES, 'UTF-8') ?>
                </p>
            <?php endif; ?>
        <?php endif; ?>
    </div>
</body>

</html>