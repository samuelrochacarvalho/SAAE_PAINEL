
const API_STATUS = "api/status.php";

// Atualiza o nível de um reservatório
function atualizarNivel(feed, idAgua, idTexto, dados) {
    const elementoAgua = document.getElementById(idAgua);
    const elementoTexto = document.getElementById(idTexto);

    if (!elementoAgua || !elementoTexto) return;

    const registro = dados[feed];
    const valor = registro ? Number(registro.valor) : NaN;

    if (!Number.isFinite(valor)) {
        elementoAgua.style.height = "0%";
        elementoTexto.textContent = "--%";
        return;
    }

    // Mantém o percentual entre 0 e 100
    const percentual = Math.max(0, Math.min(100, valor));

    elementoAgua.style.height = percentual + "%";
    elementoTexto.textContent = percentual + "%";
}




// Controle remoto: o interruptor representa o último comando observado.
// A confirmação do relé é independente do intervalo mínimo de 15 segundos.
let bombaPendente = null;
let bombaEnviando = false;
let bombaHabilitada = false;
let ultimoEstadoBomba = "";
let ultimoEstadoRele = "";
let ultimoIdRele = 0;
let ultimoIdComando = 0;
let ultimaConsultaComunicacaoOk = false;
let comandoConfigurado = false;
let proximoComandoEm = 0;
let mensagemPersistente = "";
let timerMensagemBomba = null;
const INTERVALO_COMANDOS_MS = 15000;
const API_COMANDO = "api/comando_bomba.php";

function mensagemComando(texto) {
    // Mensagens operacionais internas não substituem o aviso de sucesso.
    if (!texto.startsWith("ERRO:")) return;
    clearTimeout(timerMensagemBomba);
    mensagemPersistente = texto;
    atualizarInterfaceComando();
}
function sucessoComandoBomba() {
    clearTimeout(timerMensagemBomba);
    mensagemPersistente = "Comando enviado com sucesso!";
    atualizarInterfaceComando();
    timerMensagemBomba = setTimeout(() => {
        if (mensagemPersistente === "Comando enviado com sucesso!") {
            mensagemPersistente = "";
            atualizarInterfaceComando();
        }
    }, 5000);
}
function atualizarInterfaceComando() {
    const botao = document.getElementById("bomba-switch");
    const info = document.getElementById("bomba-comando-info");
    const restante = Math.max(0, Math.ceil((proximoComandoEm - Date.now()) / 1000));
    if (botao) botao.disabled = bombaEnviando || !bombaHabilitada || restante > 0;
    if (info) {
        const mensagem = mensagemPersistente.startsWith("ERRO:")
            ? mensagemPersistente.slice(5)
            : mensagemPersistente || (restante > 0
                ? `Aguarde ${restante} segundo(s) para enviar o próximo comando.`
                : "");
        info.textContent = mensagem;
        info.hidden = !mensagem;
    }
}
function atualizarBomba(feeds) {
    const status = document.getElementById("bomba-status");
    const botao = document.getElementById("bomba-switch");
    if (!status || !botao) return;
    const valor = String(feeds?.bombacorrego?.valor ?? "").trim().toUpperCase();
    ultimoEstadoBomba = ["HIGH", "LOW"].includes(valor) ? valor : "";
    ultimoIdComando = Number(feeds?.bombacorrego?.id || 0);
    ultimoEstadoRele = String(feeds?.estadorele?.valor ?? "").trim().toLowerCase();
    ultimoIdRele = Number(feeds?.estadorele?.id || 0);
    if (!bombaEnviando) botao.checked = valor === "HIGH";
    status.textContent = valor === "HIGH" ? "Ligado" : valor === "LOW" ? "Desligado" : "Indisponível";
    atualizarInterfaceComando();
}
function atualizarPermissaoBomba(resultado) {
    const horario = resultado.comunicacao?.corrego?.ultimo_heartbeat;
    const tempo = horario ? (Date.now() - new Date(horario).getTime()) / 1000 : Infinity;
    const limite = Number(resultado.comunicacao?.corrego?.limite_segundos || 180);
    ultimaConsultaComunicacaoOk = Number.isFinite(tempo) && tempo >= 0 && tempo <= limite;
    comandoConfigurado = resultado.controle?.bomba_configurada === true;
    bombaHabilitada = comandoConfigurado;
    atualizarInterfaceComando();
}
function verificarConfirmacaoBomba(feeds) {
    if (!bombaPendente) return;
    const p = bombaPendente;
    const rele = String(feeds?.estadorele?.valor ?? "").trim().toLowerCase();
    const releId = Number(feeds?.estadorele?.id || 0);
    const comando = String(feeds?.bombacorrego?.valor ?? "").trim().toUpperCase();
    const comandoId = Number(feeds?.bombacorrego?.id || 0);
    // Uma nova observação do relé compatível confirma o estado reportado.
    // Se o relé já estava no estado solicitado, não exigir uma nova transição.
    // Para esse caso, basta observar o comando atualizado no feed.
    if ((releId > p.idReleAnterior && rele === p.estadoEsperado) ||
        (p.releJaEstavaNoEstado && rele === p.estadoEsperado &&
         comandoId > p.idComandoAnterior && comando === p.comando)) {
        bombaPendente = null;
        mensagemComando(p.releJaEstavaNoEstado && releId <= p.idReleAnterior
            ? "Comando confirmado no feed. O relé já estava " + (rele === "ligado" ? "ligado" : "desligado") + "."
            : "Estado do relé confirmado após o comando: " + (rele === "ligado" ? "Ligado" : "Desligado") + ".");
    } else if (Date.now() >= p.expira) {
        bombaPendente = null;
        const recebido = comandoId > p.idComandoAnterior && comando === p.comando;
        mensagemComando(recebido
            ? "ERRO:Comando recebido no feed, mas SEM nova confirmação do relé. Confira o equipamento."
            : "ERRO:Sem confirmação do comando/relé. Confira a estação antes de tentar novamente.");
    }
}
async function solicitarComandoBomba(evento) {
    const botao = evento.currentTarget;
    const valor = botao.checked ? "HIGH" : "LOW";
    // Restaurar visualmente até o feed informar o comando recebido.
    botao.checked = ultimoEstadoBomba === "HIGH";
    if (bombaEnviando || !bombaHabilitada || Date.now() < proximoComandoEm) return;
    bombaEnviando = true;
    clearTimeout(timerMensagemBomba);
    mensagemPersistente = "";
    atualizarInterfaceComando();
    const idReleAntes = ultimoIdRele;
    const idComandoAntes = ultimoIdComando;
    try {
        const csrf = document.querySelector('meta[name="csrf-bomba"]')?.content || "";
        const resp = await fetch(API_COMANDO, {
            method: "POST", credentials: "same-origin", cache: "no-store",
            headers: {"Content-Type":"application/json", "X-CSRF-Token":csrf},
            body: JSON.stringify({comando:valor})
        });
        const dados = await resp.json();
        if (!resp.ok || !dados.sucesso) {
            if (Number(dados.aguardar_segundos) > 0) {
                proximoComandoEm = Date.now() + Number(dados.aguardar_segundos) * 1000;
            }
            throw new Error(dados.mensagem || "Falha no envio");
        }
        // A publicação é um aceite do Adafruit IO, não a confirmação física da bomba.
        proximoComandoEm = Date.now() + INTERVALO_COMANDOS_MS;
        bombaPendente = {
            comando: valor,
            estadoEsperado: valor === "HIGH" ? "ligado" : "desligado",
            idReleAnterior: Number(dados.rele_id_antes ?? idReleAntes),
            idComandoAnterior: Number(dados.comando_id_antes ?? idComandoAntes),
            releJaEstavaNoEstado: ultimoEstadoRele === (valor === "HIGH" ? "ligado" : "desligado"),
            expira: Date.now() + 30000
        };
        if (bombaPendente.releJaEstavaNoEstado) bombaPendente = null;
        sucessoComandoBomba();
    } catch (erro) {
        mensagemComando("ERRO:Envio não confirmado: " + erro.message);
        console.warn("Comando bomba:", erro);
    } finally {
        bombaEnviando = false;
        atualizarInterfaceComando();
    }
}


// Controle da sirene: comando e relé físico são estados independentes.
let sireneEnviando = false;
let sireneHabilitada = false;
let ultimoEstadoSirene = "";
let ultimoIdSirene = 0;
let ultimoIdReleSirene = 0;
let sirenePendente = null;
let proximoComandoSireneEm = 0;
let mensagemSirenePersistente = "";
let timerMensagemSirene = null;
const API_COMANDO_SIRENE = "api/comando_sirene.php";

function mensagemComandoSirene(texto) {
    if (!texto.startsWith("ERRO:")) return;
    clearTimeout(timerMensagemSirene);
    mensagemSirenePersistente = texto;
    atualizarInterfaceComandoSirene();
}
function sucessoComandoSirene() {
    clearTimeout(timerMensagemSirene);
    mensagemSirenePersistente = "Comando enviado com sucesso!";
    atualizarInterfaceComandoSirene();
    timerMensagemSirene = setTimeout(() => {
        if (mensagemSirenePersistente === "Comando enviado com sucesso!") {
            mensagemSirenePersistente = "";
            atualizarInterfaceComandoSirene();
        }
    }, 5000);
}
function atualizarInterfaceComandoSirene() {
    const botao = document.getElementById("sirene-switch");
    const info = document.getElementById("sirene-comando-info");
    const restante = Math.max(0, Math.ceil((proximoComandoSireneEm - Date.now()) / 1000));
    if (botao) botao.disabled = sireneEnviando || !sireneHabilitada || restante > 0;
    if (info) {
        const mensagem = mensagemSirenePersistente.startsWith("ERRO:")
            ? mensagemSirenePersistente.slice(5)
            : mensagemSirenePersistente || (restante > 0
                ? `Aguarde ${restante} segundo(s) para enviar o próximo comando.`
                : "");
        info.textContent = mensagem;
        info.hidden = !mensagem;
    }
}
function atualizarSirene(feeds) {
    const status = document.getElementById("sirene-status");
    const botao = document.getElementById("sirene-switch");
    if (!status || !botao) return;
    const valor = String(feeds?.sirene?.valor ?? "").trim().toUpperCase();
    ultimoEstadoSirene = ["HIGH", "LOW"].includes(valor) ? valor : "";
    ultimoIdSirene = Number(feeds?.sirene?.id || 0);
    ultimoIdReleSirene = Number(feeds?.statussirene?.id || 0);
    if (!sireneEnviando) botao.checked = valor === "HIGH";
    status.textContent = valor === "HIGH" ? "Ligado" : valor === "LOW" ? "Desligado" : "Indisponível";
    // O estado do relé não bloqueia o envio de HIGH ou LOW.
    sireneHabilitada = comandoConfigurado;
    atualizarInterfaceComandoSirene();
}
function verificarConfirmacaoSirene(feeds) {
    if (!sirenePendente) return;
    const p = sirenePendente;
    const rele = String(feeds?.statussirene?.valor ?? "").trim().toLowerCase();
    const releId = Number(feeds?.statussirene?.id || 0);
    const comando = String(feeds?.sirene?.valor ?? "").trim().toUpperCase();
    const comandoId = Number(feeds?.sirene?.id || 0);
    const bombaFisicamenteLigada = String(feeds?.estadorele?.valor ?? "").trim().toLowerCase() === "ligado";
    // Com a bomba desligada, HIGH na sirene apenas arma o comando.
    // O relé físico da sirene só deve ligar quando a bomba também estiver ligada.
    // Se o relé já está desligado e o comando é LOW, não há nova transição a aguardar.
    if ((p.comando === "HIGH" && !bombaFisicamenteLigada) ||
        (p.comando === "LOW" && rele === "desligado")) {
        sirenePendente = null;
        return;
    }
    // Se o relé já estava no estado solicitado, não exigir uma nova transição.
    // Para esse caso, basta observar o comando atualizado no feed.
    if ((releId > p.idReleAnterior && rele === p.estadoEsperado) ||
        (p.releJaEstavaNoEstado && rele === p.estadoEsperado &&
         comandoId > p.idComandoAnterior && comando === p.comando)) {
        sirenePendente = null;
        mensagemComandoSirene(p.releJaEstavaNoEstado && releId <= p.idReleAnterior
            ? "Comando confirmado no feed. O relé da sirene já estava " + (rele === "ligado" ? "ligado" : "desligado") + "."
            : "Estado físico da sirene confirmado: " + (rele === "ligado" ? "Ligado" : "Desligado") + ".");
    } else if (Date.now() >= p.expira) {
        sirenePendente = null;
        mensagemComandoSirene(comandoId > p.idComandoAnterior && comando === p.comando
            ? "ERRO:Comando recebido no feed, mas sem confirmação nova do relé da sirene. Confira o equipamento."
            : "ERRO:Sem confirmação da sirene. Confira a estação antes de tentar novamente.");
    }
}
async function solicitarComandoSirene(evento) {
    const botao = evento.currentTarget;
    const valor = botao.checked ? "HIGH" : "LOW";
    botao.checked = ultimoEstadoSirene === "HIGH";
    if (sireneEnviando || !sireneHabilitada || Date.now() < proximoComandoSireneEm) return;
    sireneEnviando = true;
    clearTimeout(timerMensagemSirene);
    mensagemSirenePersistente = "";
    atualizarInterfaceComandoSirene();
    const idReleAntes = ultimoIdReleSirene;
    const idComandoAntes = ultimoIdSirene;
    try {
        const csrf = document.querySelector('meta[name="csrf-bomba"]')?.content || "";
        const resp = await fetch(API_COMANDO_SIRENE, {
            method: "POST", credentials: "same-origin", cache: "no-store",
            headers: {"Content-Type":"application/json", "X-CSRF-Token":csrf},
            body: JSON.stringify({comando:valor})
        });
        const dados = await resp.json();
        if (!resp.ok || !dados.sucesso) {
            if (Number(dados.aguardar_segundos) > 0) proximoComandoSireneEm = Date.now() + Number(dados.aguardar_segundos) * 1000;
            throw new Error(dados.mensagem || "Falha no envio da sirene");
        }
        proximoComandoSireneEm = Date.now() + INTERVALO_COMANDOS_MS;
        sirenePendente = {
            comando: valor, estadoEsperado: valor === "HIGH" ? "ligado" : "desligado",
            idReleAnterior: Number(dados.rele_id_antes ?? idReleAntes),
            idComandoAnterior: Number(dados.comando_id_antes ?? idComandoAntes),
            releJaEstavaNoEstado: String(document.getElementById("sirene-rele-status")?.textContent || "").trim().toLowerCase() === (valor === "HIGH" ? "ligado" : "desligado"),
            expira: Date.now() + 30000
        };
        // A sirene física depende do relé da bomba: HIGH com bomba desligada
        // não deve gerar erro de ausência de confirmação física.
        const bombaFisicamenteLigada = ultimoEstadoRele === "ligado";
        if (sirenePendente.releJaEstavaNoEstado ||
            (valor === "HIGH" && !bombaFisicamenteLigada) ||
            (valor === "LOW" && String(document.getElementById("sirene-rele-status")?.textContent || "").trim().toLowerCase() === "desligado")) {
            sirenePendente = null;
        }
        sucessoComandoSirene();
    } catch (erro) {
        mensagemComandoSirene("ERRO:Envio da sirene não confirmado: " + erro.message);
        console.warn("Comando sirene:", erro);
    } finally {
        sireneEnviando = false;
        atualizarInterfaceComandoSirene();
    }
}


// Durante a abertura, o histórico do SQLite não prova que a estação está offline.
// Aguardamos um heartbeat MQTT novo, posterior à abertura do painel.
const ABERTURA_PAINEL_EM = Date.now();
const LIMITE_INICIALIZACAO_MS = 180000;
let heartbeatAtualConfirmado = false;
let alertaInicializacaoExpirado = false;
function validarHeartbeatDaSessao(comunicacao) {
    const horario = comunicacao?.corrego?.ultimo_heartbeat;
    const ms = horario ? new Date(horario).getTime() : NaN;
    const limite = Number(comunicacao?.corrego?.limite_segundos) || 180;
    // Pequena tolerância de relógio; exige evento recebido durante esta abertura.
    if (Number.isFinite(ms) && ms >= ABERTURA_PAINEL_EM - 2000 &&
        ms <= Date.now() + 5000 && Date.now() - ms <= limite * 1000) {
        heartbeatAtualConfirmado = true;
    }
    return heartbeatAtualConfirmado;
}

function atualizarComunicacaoCorrego(comunicacao) {
    const status = document.getElementById("corrego-status");
    const detalhe = document.getElementById("corrego-detalhe");

    if (!status || !detalhe) return;

    const dados = comunicacao?.corrego;
    if (!heartbeatAtualConfirmado) {
        status.className = "unknown";
        detalhe.textContent = "Aguardando heartbeat novo da estação";
        return;
    }
    const horario = dados?.ultimo_heartbeat;
    const limite = Number(dados?.limite_segundos) || 180;

    if (!horario) {
        status.textContent = "AGUARDANDO";
        status.className = "unknown";
        detalhe.textContent = "Nenhum heartbeat MQTT registrado";
        return;
    }

    const ultimo = new Date(horario).getTime();
    const agora = Date.now();

    if (!Number.isFinite(ultimo)) {
        status.textContent = "INDEFINIDO";
        status.className = "unknown";
        detalhe.textContent = "Horário de heartbeat inválido";
        return;
    }

    const segundos = (agora - ultimo) / 1000;

    if (segundos >= 0 && segundos <= limite) {
        status.innerHTML = '<span class="heartbeat-bolinha"></span> ONLINE';
        status.className = "heartbeat-online";
        detalhe.textContent = "Último heartbeat há " +
            Math.floor(segundos) + " segundos";
    } else {
        status.innerHTML = '<span class="heartbeat-bolinha"></span> OFFLINE';
        status.className = "heartbeat-offline";
        detalhe.textContent = segundos < 0
            ? "Horário do heartbeat está no futuro"
            : "Sem heartbeat há " + Math.floor(segundos) + " segundos";
    }
}

function atualizarEstadosRele(feeds) {
    const equipamentos = [
        {
            feed: "estadorele",
            elemento: "bomba-rele-status"
        },
        {
            feed: "statussirene",
            elemento: "sirene-rele-status"
        }
    ];

    equipamentos.forEach(equipamento => {
        const elemento = document.getElementById(equipamento.elemento);

        if (!elemento) return;

        const registro = feeds[equipamento.feed];

        const valor = registro
            ? String(registro.valor).trim().toLowerCase()
            : "";

        if (valor === "ligado") {
            elemento.textContent = "Ligado";
            elemento.style.color = "#22c55e";

        } else if (valor === "desligado") {
            elemento.textContent = "Desligado";
            elemento.style.color = "#ef4444";

        } else {
            elemento.textContent = "Indisponível";
            elemento.style.color = "#9ca3af";
        }
    });
}



/* CENTRAL DE ALERTAS — comunicação e divergência da bomba.
   Apenas monitoramento: não envia comandos aos equipamentos. */

const mensagensAlertas = {
    comunicacao: {
        titulo: "BOMBA DO CÓRREGO — FALHA DE COMUNICAÇÃO",
        mensagem: "Estação sem comunicação há mais de 3 minutos!\n\n" +
            "Envios de comandos podem falhar, feche o sistema e abra a tela novamente.\n\n" +
            "Possíveis falhas:\n" +
            "1º Problema de conexão com internet na Subestação.\n" +
            "2º Falta de Energia na Subestação."
    },
    divergencia: {
        titulo: "BOMBA DO CÓRREGO — DIVERGÊNCIA",
        mensagem: "Estação com Relé Desligado e Botão de acionamento da Bomba Ligado.\n\n" +
            "Envios de comandos podem falhar, feche o sistema e abra a tela novamente.\n\n" +
            "Possíveis falhas:\n" +
            "1º Reinício Programado do Sistema (00:03 hrs).\n" +
            "2º Queda de Energia na Subestação."
    }
};
const alertasAtivos = new Set();
const inicioOcorrencias = new Map();
let modalFechadoManualmente = false;
let alertaSilenciadoAte = 0;
let silencioAnterior = false;
// Sirene MP3 local, em loop enquanto houver alerta sonoro ativo.
const sireneAudio = new Audio("assets/audio/sirene.mp3");
sireneAudio.loop = true;
sireneAudio.preload = "auto";
let audioLiberado = false;
let ultimaConsultaOk = false;

function horarioFormatado(data) {
    const d = new Date(data);
    return Number.isFinite(d.getTime()) ? d.toLocaleString("pt-BR") : "--";
}
function modalAlerta() { return document.getElementById("alerta-modal"); }
function alertaEstaSilenciado() { return Date.now() < alertaSilenciadoAte; }

function sincronizarSom() {
    const deveTocar = alertasAtivos.size > 0 && !alertaEstaSilenciado() && !modalFechadoManualmente;
    if (!deveTocar) {
        sireneAudio.pause();
        sireneAudio.currentTime = 0;
        return;
    }
    if (!audioLiberado || !sireneAudio.paused) return;
    const tentativa = sireneAudio.play();
    if (tentativa && typeof tentativa.catch === "function") {
        tentativa.catch(erro => {
            if (erro.name === "NotAllowedError") {
                audioLiberado = false;
                const info = document.getElementById("alerta-audio-info");
                if (info) info.textContent = "Clique na página para habilitar o áudio da sirene.";
            } else if (erro.name !== "AbortError") {
                console.warn("Não foi possível reproduzir a sirene MP3:", erro);
            }
        });
    }
}
function liberarAudio() {
    audioLiberado = true;
    const info = document.getElementById("alerta-audio-info");
    if (info) info.textContent = "";
    sincronizarSom();
}
function renderizarAlertas() {
    const modal = modalAlerta();
    const indicador = document.getElementById("alerta-indicador");
    const contagem = document.getElementById("alerta-indicador-contagem");
    const ativos = [...alertasAtivos];

    if (indicador) indicador.hidden = ativos.length === 0;
    if (contagem) contagem.textContent = `(${ativos.length})`;

    if (ativos.length === 0) {
        if (modal) modal.hidden = true;
        modalFechadoManualmente = false;
        alertaSilenciadoAte = 0;
        silencioAnterior = false;
        sincronizarSom();
        atualizarStatusSilenciamento();
        return;
    }
    const subtitulo = document.getElementById("alerta-subtitulo");
    const conteudo = document.getElementById("alerta-mensagem");
    const data = document.getElementById("alerta-data");
    if (subtitulo) subtitulo.textContent = ativos.length === 1
        ? mensagensAlertas[ativos[0]].titulo : `${ativos.length} ALERTAS CRÍTICOS ATIVOS`;
    if (conteudo) conteudo.textContent = ativos.map(id =>
        `${mensagensAlertas[id].titulo}\n\n${mensagensAlertas[id].mensagem}`
    ).join("\n\n────────────────────\n\n");
    if (data) data.textContent = ativos.map(id =>
        `${mensagensAlertas[id].titulo}: ${horarioFormatado(inicioOcorrencias.get(id))}`
    ).join(" | ");
    if (modal) modal.hidden = modalFechadoManualmente;
    sincronizarSom();
    atualizarStatusSilenciamento();
}
function definirAlerta(id, ativo, inicio = null) {
    const existia = alertasAtivos.has(id);
    if (ativo && !existia) {
        alertasAtivos.add(id);
        inicioOcorrencias.set(id, inicio || new Date().toISOString());
        // Um alerta novo interrompe o silenciamento anterior.
        alertaSilenciadoAte = 0;
        silencioAnterior = false;
        modalFechadoManualmente = false;
        renderizarAlertas();
    } else if (!ativo && existia) {
        alertasAtivos.delete(id);
        inicioOcorrencias.delete(id);
        // Não fecha o modal se outro alerta continuar ativo.
        renderizarAlertas();
    }
}
function verificarAlertaComunicacao(comunicacao) {
    if (!heartbeatAtualConfirmado) {
        // Sem mensagem nova, não usar a idade do último registro de ontem.
        // Se a estação não responder durante a janela inicial, sinalizar falha
        // a partir desta abertura, não do horário histórico.
        const expirou = Date.now() - ABERTURA_PAINEL_EM > LIMITE_INICIALIZACAO_MS;
        alertaInicializacaoExpirado = expirou;
        definirAlerta("comunicacao", expirou,
            new Date(ABERTURA_PAINEL_EM + LIMITE_INICIALIZACAO_MS).toISOString());
        return;
    }
    const corrego = comunicacao?.corrego;
    const horario = corrego?.ultimo_heartbeat;
    const ms = horario ? new Date(horario).getTime() : NaN;
    if (!Number.isFinite(ms)) return;
    const limite = Number(corrego.limite_segundos) || 180;
    const segundos = (Date.now() - ms) / 1000;
    definirAlerta("comunicacao", segundos > limite, new Date(ms + limite * 1000).toISOString());
}
function verificarAlertaDivergencia(alertas) {
    const bomba = alertas?.bomba_corrego;
    if (!bomba || typeof bomba.critico !== "boolean") return;
    definirAlerta("divergencia", bomba.critico, bomba.inicio);
}
function fecharModalAlerta() {
    modalFechadoManualmente = true;
    const modal = modalAlerta();
    if (modal) modal.hidden = true;
    sincronizarSom();
}
function abrirModalAlerta() {
    if (alertasAtivos.size === 0) return;
    modalFechadoManualmente = false;
    renderizarAlertas();
}
function silenciarAlerta() {
    if (alertasAtivos.size === 0) return;
    alertaSilenciadoAte = Date.now() + 5 * 60 * 1000;
    silencioAnterior = true;
    sincronizarSom();
    atualizarStatusSilenciamento();
}
function atualizarStatusSilenciamento() {
    const elemento = document.getElementById("alerta-silencio-status");
    const botao = document.getElementById("alerta-silenciar");
    const silenciado = alertaEstaSilenciado();
    if (silencioAnterior && !silenciado) {
        silencioAnterior = false;
        alertaSilenciadoAte = 0;
        if (alertasAtivos.size > 0) {
            modalFechadoManualmente = false;
            renderizarAlertas();
            return;
        }
    }
    if (elemento) {
        const restante = Math.max(0, Math.ceil((alertaSilenciadoAte - Date.now()) / 1000));
        const minutos = String(Math.floor(restante / 60)).padStart(2, "0");
        const segundos = String(restante % 60).padStart(2, "0");
        elemento.textContent = silenciado ? `Som silenciado — ${minutos}:${segundos} restantes` : "";
    }
    if (botao) botao.disabled = silenciado || alertasAtivos.size === 0;
    sincronizarSom();
}

// Consulta os últimos registros do SQLite via PHP.
let consultaEmAndamento = false;
async function atualizarPainel() {
    if (consultaEmAndamento) return;
    consultaEmAndamento = true;
    try {
        const resposta = await fetch(API_STATUS, { cache: "no-store" });
        if (!resposta.ok) throw new Error("Erro HTTP: " + resposta.status);
        const resultado = await resposta.json();
        if (!resultado.sucesso) throw new Error(resultado.mensagem || "Erro na API");
        validarHeartbeatDaSessao(resultado.comunicacao);
        const feeds = resultado.feeds || {};
        atualizarNivel("nivelalta", "nivel-alta-agua", "nivel-alta-texto", feeds);
        atualizarNivel("nivelquadrada", "nivel-quadrada-agua", "nivel-quadrada-texto", feeds);
        atualizarBomba(feeds);
        atualizarPermissaoBomba(resultado);
        verificarConfirmacaoBomba(feeds);
        atualizarSirene(feeds);
        verificarConfirmacaoSirene(feeds);
        atualizarComunicacaoCorrego(resultado.comunicacao);
        atualizarEstadosRele(feeds);
        verificarAlertaComunicacao(resultado.comunicacao);
        // Não disparar divergência histórica antes de receber telemetria atual.
        if (heartbeatAtualConfirmado) {
            verificarAlertaDivergencia(resultado.alertas);
        }
        ultimaConsultaOk = true;
    } catch (erro) {
        ultimaConsultaOk = false;
        bombaHabilitada = false;
        sireneHabilitada = false;
        document.getElementById("bomba-switch")?.setAttribute("disabled", "");
        document.getElementById("sirene-switch")?.setAttribute("disabled", "");
        if (bombaPendente && Date.now() >= bombaPendente.expira) { bombaPendente = null; mensagemComando("ERRO:Sem confirmação: API de status indisponível."); }
        console.error("Erro ao atualizar painel:", erro);
        // Não limpar alertas existentes se a API falhar.
    } finally { consultaEmAndamento = false; }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("bomba-switch")?.addEventListener("change", solicitarComandoBomba);
    document.getElementById("sirene-switch")?.addEventListener("change", solicitarComandoSirene);
    document.getElementById("alerta-fechar")?.addEventListener("click", fecharModalAlerta);
    document.getElementById("alerta-reabrir")?.addEventListener("click", abrirModalAlerta);
    document.getElementById("alerta-silenciar")?.addEventListener("click", silenciarAlerta);
    document.addEventListener("pointerdown", liberarAudio);
    document.addEventListener("keydown", liberarAudio);
    atualizarStatusSilenciamento();
    setInterval(atualizarStatusSilenciamento, 1000);
    setInterval(atualizarInterfaceComando, 1000);
    setInterval(atualizarInterfaceComandoSirene, 1000);
    atualizarPainel();
    setInterval(atualizarPainel, 5000);
});
