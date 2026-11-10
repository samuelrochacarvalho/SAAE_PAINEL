<?php
session_start();
if (empty($_SESSION['csrf_bomba'])) {
    $_SESSION['csrf_bomba'] = bin2hex(random_bytes(32));
}
$titulo = 'SAAE | Painel Reservatorios';
?>
<!doctype html>
<html lang="pt-BR">

<head>
    <meta charset="utf-8">
    <meta name="csrf-bomba" content="<?= htmlspecialchars($_SESSION['csrf_bomba'], ENT_QUOTES, 'UTF-8') ?>">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title><?= htmlspecialchars($titulo) ?></title>
    <link rel="stylesheet" href="assets/css/style.css">
</head>

<body>
    <div class="layout">
        <aside class="sidebar">
            <div class="brand">◈ <span onclick="window.location.reload()">SAAE TROMBAS<small>Reservatorios</small></span></div>
            <nav><a class="active" href="#visao">▦ Visão geral</a><a href="#reservatorios">◉ Reservatórios</a><a href="#controles">⚡ Controles</a><!--<a href="#eventos">≡ Eventos</a>--></nav>
            <div class="sidefoot">MONITORAMENTO ATIVO<br><small>Heartbeat via Adafruit IO</small></div>
        </aside>
        <main>
            <header>
                <div>
                    <p class="eyebrow">CENTRAL DE MONITORAMENTO</p>
                    <h1>Painel de operações</h1>
                    <p class="muted">Acompanhamento das estações e reservatórios</p>
                </div><span class="comunicando">● Sistema em Pleno Funcionamento </span><!---se tiver falha de comunicaçao em algum heartbeat mudar class para falhacomunicacao -->
            </header>
            <section id="visao" class="stats">
                <article class="stat"><span>COMUNICAÇÃO CAIXA ALTA</span><strong id="cxAlta-status" class="unknown">
                        <p></p>
                    </strong><small id="cxAlta-detalhe">Consultando heartbeat</small></article>
                <article class="stat"><span>COMUNICAÇÃO CÓRREGO</span><strong id="corrego-status" class="unknown">
                        <p></p>
                    </strong><small id="corrego-detalhe">Consultando heartbeat</small></article>
            </section>
            <div class="content">
                <section id="reservatorios" class="panel">
                    <div class="heading">
                        <div>
                            <h2>Reservatórios</h2>
                            <p>Indicadores ilustrativos — sem dados reais</p>
                        </div><span class="pill">Prévia visual</span>
                    </div>
                    <div class="tanks">
                        <div class="tankcard">
                            <div class="tank">
                                <div class="water" id="nivel-alta-agua" style="height:0%"></div>
                                <span id="nivel-alta-texto">--%</span>
                            </div>
                            <h3>Caixa Alta</h3><small><!----></small>
                        </div>
                        <div class="tankcard">
                            <div class="tank">
                                <div class="water" id="nivel-quadrada-agua" style="height:0%"></div>
                                <span id="nivel-quadrada-texto">--%</span>
                            </div>
                            <h3>Caixa Quadrada</h3><small><!----></small>
                        </div>
                    </div>
                </section>
                <section id="controles" class="panel">
                    <div class="heading">
                        <div>
                            <h2>Controle remoto caixa quadrada</h2>
                            <p>Acionamento remoto com confirmação do estado do relé</p>
                        </div>
                    </div>

                    <div class="control control-bomba">
                        <div>
                            <h3>Bomba do Córrego</h3>
                            <p>
                                Estado do relé:
                                <strong id="bomba-rele-status">Verificando...</strong>
                            </p>
                        </div>

                        <div class="actions">
                            <label class="switch">
                                <input type="checkbox" id="bomba-switch" disabled>
                                <span class="switch-slider"></span>
                            </label>
                            <span class="switch-status" id="bomba-status">Indisponível</span>
                        </div>

                        <p id="bomba-comando-info"
                            role="status"
                            aria-live="polite">
                            Verificando disponibilidade do controle da bomba...
                        </p>
                    </div>
                    <div class="control control-sirene">
                        <div>
                            <h3>Sirene</h3>
                            <p>
                                Estado do relé:
                                <strong id="sirene-rele-status">Verificando...</strong>
                            </p>
                        </div>

                        <div class="actions">
                            <label class="switch">
                                <input type="checkbox" id="sirene-switch" disabled>
                                <span class="switch-slider"></span>
                            </label>
                            <span class="switch-status" id="sirene-status">Indisponível</span>
                        </div>

                        <p id="sirene-comando-info"
                            role="status"
                            aria-live="polite">
                            Verificando disponibilidade do controle da sirene...
                        </p>
                    </div>
                </section>
            </div>
            <footer>Painel Supervisório SAAE · Controle local da bomba com confirmação</footer>
        </main>
    </div>
    <script src="assets/js/painel.js" defer></script>

    <!-- CENTRAL DE ALERTAS -->
    <div id="alerta-indicador" hidden style="position:fixed;right:18px;bottom:18px;z-index:9998;background:#991b1b;color:white;border-radius:10px;padding:12px 16px;box-shadow:0 5px 25px #0007;">
        <button id="alerta-reabrir" type="button" style="color:inherit;background:transparent;border:0;cursor:pointer;font-weight:bold;">⚠ Alertas ativos — visualizar</button>
        <span id="alerta-indicador-contagem"></span>
    </div>
    <div id="alerta-modal" class="alerta-overlay" hidden>

        <div class="alerta-janela" role="dialog"
            aria-modal="true"
            aria-labelledby="alerta-titulo">

            <div class="alerta-cabecalho">
                <h2 id="alerta-titulo">
                    ⚠ ALERTA CRÍTICO
                </h2>
            </div>

            <div class="alerta-conteudo">

                <h3 id="alerta-subtitulo">
                    BOMBA DO CÓRREGO
                </h3>

                <div id="alerta-mensagem" style="white-space:pre-line"></div>

                <p class="alerta-horario">
                    Ocorrência:
                    <span id="alerta-data">--</span>
                </p>

            </div>

            <div class="alerta-rodape">

                <button type="button"
                    id="alerta-silenciar">
                    Silenciar por 5 minutos
                </button>

                <button type="button"
                    id="alerta-fechar">
                    Fechar alerta
                </button>

            </div>

            <p id="alerta-silencio-status"
                aria-live="polite"></p>

        </div>

    </div>
    <!-- FIM CENTRAL DE ALERTAS -->
    <p id="alerta-audio-info" aria-live="polite" style="position:fixed;left:16px;bottom:12px;z-index:9997;font-size:12px;color:#d1d5db;"></p>

</body>

</html>