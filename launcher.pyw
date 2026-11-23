"""Launcher portátil do Painel Supervisório SAAE.

Teste: python launcher_saae.py (dentro da pasta SAAE_PAINEL).
Empacotamento futuro: PyInstaller --onedir --noconsole (veja instruções).
"""
import os
import sys
import time
import socket
import sqlite3
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import urllib.request
import urllib.error
import atexit
import json
import shutil
import webview
import re
from datetime import datetime

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
PHP_EXE = APP_DIR / 'runtime' / 'php' / 'php.exe'
DB_FILE = APP_DIR / 'dados' / 'saae.db'
MQTT_SCRIPT = APP_DIR / 'mqtt' / 'cliente.py'
INDEX_FILE = APP_DIR / 'index.php'
HOST = '127.0.0.1'
PORT = 8090

# Endereço que o aplicativo Python abrirá
URL = f'http://{HOST}:{PORT}/index.php?local=1'

# Endereço utilizado para verificar o servidor PHP
URL_CHECK = f'http://{HOST}:{PORT}/'

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
PROCS = []
WINDOW = None
STARTED = False
STOP_EVENT = threading.Event()
PROCS_LOCK = threading.RLock()
LOG_DIR = APP_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)


# CONFIGURAÇÃO CLOUDFLARE
CLOUDFLARED_EXE = (
    APP_DIR / 'dependencias' / 'cloudflared.exe'
    if (APP_DIR / 'dependencias' / 'cloudflared.exe').is_file()
    else shutil.which('cloudflared')
)

CLOUDFLARE_URL_LOCAL = 'http://127.0.0.1:8090'


def registrar_launcher(mensagem):
    """Registro simples, independente do processo MQTT."""
    from datetime import datetime
    try:
        with (LOG_DIR / 'launcher.log').open('a', encoding='utf-8') as arquivo:
            arquivo.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {mensagem}\n")
    except OSError:
        pass


def supervisionar_mqtt(processo_inicial, comando):
    """Reinicia somente o trabalhador MQTT que efetivamente terminou."""
    proc = processo_inicial
    espera = 3
    while not STOP_EVENT.wait(5):
        codigo = proc.poll()
        if codigo is None:
            continue
        registrar_launcher(f'MQTT encerrou (código {codigo}); reinício em {espera}s')
        if STOP_EVENT.wait(espera):
            return
        try:
            proc = start_process(comando, APP_DIR / 'mqtt')
            registrar_launcher(f'MQTT reiniciado, PID {proc.pid}')
            espera = 3
        except Exception as erro:
            registrar_launcher(f'Falha ao reiniciar MQTT: {erro!r}')
            espera = min(espera * 2, 60)



def mqtt_worker():
    # No EXE, o próprio executável reinicia em modo trabalhador MQTT.
    # A importação explícita ajuda o PyInstaller a identificar a dependência.
    import Adafruit_IO  # noqa: F401
    import runpy
    os.chdir(APP_DIR / 'mqtt')
    sys.path.insert(0, str(APP_DIR / 'mqtt'))
    runpy.run_path(str(MQTT_SCRIPT), run_name='__main__')


if len(sys.argv) > 1 and sys.argv[1] == '--mqtt-worker':
    mqtt_worker()
    sys.exit(0)


def stop_processes():
    """Encerra somente os processos iniciados por este launcher, incluindo filhos."""
    STOP_EVENT.set()
    # Encerra explicitamente o túnel e remove o acesso remoto desta execução.
    # O lock impede disputa com a geração e a expiração do token.
    try:
        encerrar_cloudflare('fechamento do launcher')
    except Exception as erro:
        registrar_launcher(f'Falha ao encerrar Cloudflare no fechamento: {erro!r}')
    try:
        ARQUIVO_ACESSO_REMOTO.unlink(missing_ok=True)
    except OSError as erro:
        registrar_launcher(f'Falha ao remover token no fechamento: {erro!r}')

    with PROCS_LOCK:
        processes = list(reversed(PROCS))
        PROCS.clear()

    for proc in processes:
        if os.name == 'nt':
            # No Windows, terminate() encerra apenas o processo principal.
            # /T inclui eventuais filhos; /PID limita a ação ao nosso processo.
            try:
                subprocess.run(
                    ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=CREATE_FLAGS,
                    timeout=8,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass


atexit.register(stop_processes)


def check_port():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def check_http():
    try:
        with urllib.request.urlopen(URL_CHECK, timeout=1.5) as r:
            return r.status == 200
    except Exception as erro:
        registrar_launcher(f'Falha na verificação HTTP: {erro!r}')
        return False


def start_process(command, cwd):
    with PROCS_LOCK:
        if STOP_EVENT.is_set():
            raise RuntimeError('Inicialização cancelada.')
        # Os erros do trabalhador MQTT são registrados pelo próprio cliente.py.
        proc = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=CREATE_FLAGS)
        PROCS.append(proc)
        return proc

# ==========================================
# CLOUDFLARE TUNNEL
# ==========================================

CLOUDFLARE_PROCESSO = None
CLOUDFLARE_URL = None
CLOUDFLARE_LOCK = threading.RLock()


def encerrar_cloudflare(motivo):
    """Encerra somente o cloudflared criado por esta instância do launcher."""
    global CLOUDFLARE_PROCESSO, CLOUDFLARE_URL

    with CLOUDFLARE_LOCK:
        processo = CLOUDFLARE_PROCESSO
        if processo is None:
            CLOUDFLARE_URL = None
            return True

        if processo.poll() is None:
            registrar_launcher(f'Encerrando Cloudflare PID {processo.pid}: {motivo}')
            if os.name == 'nt':
                try:
                    subprocess.run(
                        ['taskkill', '/PID', str(processo.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        creationflags=CREATE_FLAGS,
                        timeout=8,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as erro:
                    registrar_launcher(f'Falha no taskkill do Cloudflare: {erro!r}')
            else:
                processo.terminate()

            try:
                processo.wait(timeout=4)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=3)

        if processo.poll() is None:
            raise RuntimeError(f'Cloudflare PID {processo.pid} continua em execução')

        # Retira o processo já encerrado da lista de filhos supervisionados.
        with PROCS_LOCK:
            if processo in PROCS:
                PROCS.remove(processo)
        CLOUDFLARE_PROCESSO = None
        CLOUDFLARE_URL = None
        registrar_launcher(f'Cloudflare PID {processo.pid} encerrado: {motivo}')
        return True

from datetime import datetime, timedelta
import secrets

PRIV_DIR = APP_DIR.parent / 'saae_privado'
ARQUIVO_ACESSO_REMOTO = APP_DIR.parent / "saae_privado" / "acesso_remoto.json"
ARQUIVO_LOGIN_LOCAL = PRIV_DIR / 'login_local.json'
ARQUIVO_BOOT = PRIV_DIR / 'boot.json'
def preparar_login_local():
    PRIV_DIR.mkdir(parents=True, exist_ok=True)
    # One-time token used only by the embedded PyWebView window.
    segredo = secrets.token_urlsafe(48)
    ARQUIVO_BOOT.write_text(json.dumps({'id': secrets.token_hex(32)}), encoding='utf-8')
    ARQUIVO_LOGIN_LOCAL.write_text(
        json.dumps({'hash': __import__('hashlib').sha256(segredo.encode()).hexdigest()}),
        encoding='utf-8'
    )
    return segredo


LOGIN_LOCAL_SEGREDO = None


def limpar_acesso_remoto_inicial():
    global CLOUDFLARE_URL

    try:
        # Pasta privada fora do diretório do projeto
        pasta_privada = APP_DIR.parent / "saae_privado"
        arquivo_token = pasta_privada / "acesso_remoto.json"

        if arquivo_token.is_file():
            arquivo_token.unlink()

            registrar_launcher(
                "Token remoto anterior excluído na inicialização."
            )

        CLOUDFLARE_URL = None

    except Exception as erro:
        registrar_launcher(
            f"Erro ao limpar acesso remoto: {erro!r}"
        )
        raise
def consultar_token_ativo():
    if not ARQUIVO_ACESSO_REMOTO.is_file():
        return None

    try:
        dados = json.loads(
            ARQUIVO_ACESSO_REMOTO.read_text(encoding='utf-8')
        )

        expiracao = datetime.fromisoformat(dados['expira_em'])

        if datetime.now().astimezone() >= expiracao:
            return None

        if (
            CLOUDFLARE_PROCESSO is None
            or CLOUDFLARE_PROCESSO.poll() is not None
            or dados.get('url') != CLOUDFLARE_URL
        ):
            return None

        return dados

    except (OSError, ValueError, KeyError, TypeError):
        return None

def salvar_acesso_remoto(url):
    # Gera um código aleatório de 6 dígitos
    codigo = f'{secrets.randbelow(1000000):06d}'

    agora = datetime.now().astimezone()
    expiracao = agora + timedelta(minutes=60)

    dados = {
        'url': url,
        'codigo': codigo,
        'criado_em': agora.isoformat(timespec='seconds'),
        'expira_em': expiracao.isoformat(timespec='seconds')
    }

    ARQUIVO_ACESSO_REMOTO.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporario = ARQUIVO_ACESSO_REMOTO.with_suffix('.tmp')

    temporario.write_text(
        json.dumps(dados, indent=4, ensure_ascii=False),
        encoding='utf-8'
    )

    temporario.replace(ARQUIVO_ACESSO_REMOTO)

    registrar_launcher('JSON de acesso remoto atualizado')

    return dados


def iniciar_cloudflare():
    global CLOUDFLARE_PROCESSO, CLOUDFLARE_URL

    with CLOUDFLARE_LOCK:

        # Evita iniciar dois túneis simultaneamente.
        if CLOUDFLARE_PROCESSO is not None:
            if CLOUDFLARE_PROCESSO.poll() is None:
                return CLOUDFLARE_URL

        if not CLOUDFLARED_EXE:
            raise RuntimeError(
                'cloudflared.exe não encontrado.'
            )

        CLOUDFLARE_URL = None

        comando = [
            str(CLOUDFLARED_EXE),
            'tunnel',
            '--url',
            CLOUDFLARE_URL_LOCAL
        ]

        processo = subprocess.Popen(
            comando,
            cwd=str(APP_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_FLAGS
        )

        CLOUDFLARE_PROCESSO = processo

        with PROCS_LOCK:
            PROCS.append(processo)

        registrar_launcher(
            f'Cloudflare iniciado, PID {processo.pid}'
        )

        def ler_saida():
            global CLOUDFLARE_URL

            padrao = re.compile(
                r'https://[a-z0-9-]+\.trycloudflare\.com',
                re.IGNORECASE
            )

            try:
                for linha in iter(processo.stderr.readline, b''):

                    mensagem = linha.decode(
                        'utf-8',
                        errors='replace'
                    )

                    encontrado = padrao.search(mensagem)

                    if encontrado and CLOUDFLARE_URL is None:
                        CLOUDFLARE_URL = encontrado.group(0)

                        registrar_launcher(
                            'URL HTTPS do Cloudflare capturada'
                        )

            except Exception as erro:
                registrar_launcher(
                    f'Erro na leitura Cloudflare: {erro!r}'
                )

        threading.Thread(
            target=ler_saida,
            daemon=True,
            name='cloudflare-reader'
        ).start()

        return CLOUDFLARE_URL

def update_status(message, value):
    def apply():
        if splash.winfo_exists():
            status_label.config(text=message)
            progress['value'] = value
            percent_label.config(text=f'{value}%')
    splash.after(0, apply)


def show_error(message):
    def apply():
        if splash.winfo_exists():
            title_label.config(text='Falha na inicialização')
            status_label.config(text=message)
            percent_label.config(text='')
            retry_button.place(x=36, y=377)
    splash.after(0, apply)


def check_internet():
    """Confere acesso HTTPS externo, sem depender de ICMP/ping."""
    endpoints = (
        'https://www.google.com/generate_204',
        'https://www.cloudflare.com/cdn-cgi/trace',
    )
    for address in endpoints:
        try:
            request = urllib.request.Request(
                address,
                headers={'User-Agent': 'SAAE-Supervisor/1.0', 'Cache-Control': 'no-cache'}
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                if 200 <= response.status < 400:
                    return True
        except (OSError, urllib.error.URLError, ValueError):
            continue
    return False


VERSAO_URL = (
    'https://raw.githubusercontent.com/'
    'samuelrochacarvalho/SAAE_PAINEL/main/versao.json'
)
VERSAO_LOCAL = APP_DIR / 'versao.json'


def verificar_atualizacao():
    """Consulta o GitHub e informa se há uma versão mais recente."""
    try:
        with VERSAO_LOCAL.open('r', encoding='utf-8') as arquivo:
            versao_local = json.load(arquivo)['versao']

        requisicao = urllib.request.Request(
            VERSAO_URL,
            headers={
                'User-Agent': 'SAAE-Painel/1.0',
                'Cache-Control': 'no-cache',
            },
        )
        with urllib.request.urlopen(requisicao, timeout=5) as resposta:
            versao_remota = json.load(resposta)['versao']

        def converter_versao(versao):
            partes = versao.split('.')
            if len(partes) != 3 or not all(p.isdigit() for p in partes):
                raise ValueError('Formato de versão inválido')
            return tuple(int(p) for p in partes)

        return converter_versao(versao_remota) > converter_versao(versao_local)

    except (OSError, ValueError, KeyError, TypeError, AttributeError) as erro:
        print(f'Não foi possível verificar atualizações: {erro}')
        return None


def check_files():
    for path in (PHP_EXE, INDEX_FILE, MQTT_SCRIPT, APP_DIR / 'api' / 'proteger_acesso.php'):
        if not path.is_file():
            raise FileNotFoundError(f'Arquivo não encontrado: {path.relative_to(APP_DIR)}')
    if not DB_FILE.is_file():
        raise FileNotFoundError('Banco SQLite não encontrado: dados/saae.db')
    with sqlite3.connect(f'file:{DB_FILE.as_posix()}?mode=ro', uri=True, timeout=5) as db:
        db.execute('SELECT 1 FROM estacao_heartbeat LIMIT 1').fetchone()


def executar_atualizador():
    """Abre o atualizador separado; ele aguarda este launcher sair antes de substituir arquivos."""
    arquivo = APP_DIR / 'atualizador.pyw'
    if not arquivo.is_file():
        raise FileNotFoundError('atualizador.pyw não encontrado na pasta do SAAE_PAINEL.')

    interpretador = Path(sys.executable)
    if os.name == 'nt' and interpretador.name.lower() == 'python.exe':
        pythonw = interpretador.with_name('pythonw.exe')
        if pythonw.is_file():
            interpretador = pythonw
    # O atualizador fornecido é um script Python; não o execute usando um EXE
    # congelado do launcher, pois ele reiniciaria o aplicativo em vez do atualizador.
    if getattr(sys, 'frozen', False):
        raise RuntimeError('Launcher empacotado: configure um Python externo para o atualizador.pyw.')

    proc = subprocess.Popen(
        [str(interpretador), str(arquivo), '--parent-pid', str(os.getpid())],
        cwd=str(APP_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_FLAGS,
    )
    registrar_launcher(f'Atualizador iniciado, PID {proc.pid}; encerrando launcher.')
    # O atualizador não pertence à lista PROCS, pois deve sobreviver ao fechamento.
    STOP_EVENT.set()
    splash.after(0, close_splash)
    return True


def startup():
    global STARTED
    try:
         # Remove o token da execução anterior
        update_status('Limpando acesso remoto anterior...', 5)
        limpar_acesso_remoto_inicial()
        global LOGIN_LOCAL_SEGREDO
        LOGIN_LOCAL_SEGREDO = preparar_login_local()
        threading.Thread(
            target=monitorar_expiracao_token,
            daemon=True,
            name="MonitorExpiracaoToken"
        ).start()
        
        update_status('Verificando internet local...', 10)
        # Mantém o splash aberto e repete a verificação a cada 10 segundos.
        # O intervalo é contado entre o término de uma tentativa falha
        # e o início da próxima, sem bloquear a interface Tkinter.
        while not STOP_EVENT.is_set():
            update_status('Verificando internet local...', 10)
            if check_internet():
                break
            update_status('Verifique internet local — nova tentativa em 10 segundos.', 10)
            if STOP_EVENT.wait(10):
                return
        if STOP_EVENT.is_set():
            return
        update_status('Internet local disponível.', 20)

        update_status('Verificando atualizações...', 22)
        atualizacao_disponivel = verificar_atualizacao()
        if STOP_EVENT.is_set():
            return
        if atualizacao_disponivel is True:
            update_status('Nova versão encontrada. Abrindo atualizador...', 23)
            executar_atualizador()
            return
        elif atualizacao_disponivel is False:
            update_status('Sistema atualizado.', 23)
        else:
            update_status('Não foi possível verificar atualizações. Continuando...', 23)
        if STOP_EVENT.wait(2):
            return

        update_status('Verificando banco SQLite e arquivos...', 25)
        check_files()
        update_status('Banco de dados verificado.', 35)

        update_status('Iniciando cliente MQTT...', 50)
        if getattr(sys, 'frozen', False):
            mqtt_cmd = [sys.executable, '--mqtt-worker']
        else:
            mqtt_cmd = [sys.executable, '-u', str(MQTT_SCRIPT)]
        mqtt_proc = start_process(mqtt_cmd, APP_DIR / 'mqtt')
        time.sleep(1.0)
        if mqtt_proc.poll() is not None:
            raise RuntimeError('O cliente MQTT encerrou ao iniciar. Verifique as dependências Python e mqtt/config.py.')

        threading.Thread(target=supervisionar_mqtt, args=(mqtt_proc, mqtt_cmd),
                         daemon=True, name='supervisor-mqtt').start()
        registrar_launcher(f'MQTT iniciado, PID {mqtt_proc.pid}; supervisão ativa')
        if STOP_EVENT.is_set():
            return
        update_status('Iniciando servidor PHP...', 70)
        if check_port():
            raise RuntimeError(f'A porta {PORT} já está ocupada. Feche o iniciar.bat ou outro servidor nessa porta.')
        php_proc = start_process([str(PHP_EXE), '-d', f'auto_prepend_file={APP_DIR / "api" / "proteger_acesso.php"}', '-S', f'{HOST}:{PORT}', '-t', str(APP_DIR)], APP_DIR)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if php_proc.poll() is not None:
                raise RuntimeError('O servidor PHP encerrou inesperadamente.')
            if check_http():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('O servidor PHP não respondeu dentro de 20 segundos.')

        if STOP_EVENT.is_set():
            return
        update_status('Abrindo Painel...', 95)
        STARTED = True
        update_status('Sistema pronto!', 100)
        splash.after(200, open_panel)
    except Exception as exc:
        stop_processes()
        if not STOP_EVENT.is_set() or splash.winfo_exists():
            show_error(str(exc))



def focus_panel_window():
    """Tenta trazer o painel para frente e dar foco apenas na abertura (Windows)."""
    if os.name != 'nt':
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL

    hwnd = user32.FindWindowW(None, 'SAAE | Painel de Comandos e Níveis')
    if not hwnd:
        return False

    # Coloca momentaneamente à frente; não deixa o painel sempre no topo.
    flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # TOPMOST
    user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)  # NOTOPMOST
    return bool(user32.SetForegroundWindow(hwnd))


def monitorar_expiracao_token():
    while not STOP_EVENT.wait(5):
        try:
            with CLOUDFLARE_LOCK:
                if not ARQUIVO_ACESSO_REMOTO.is_file():
                    continue
                dados = json.loads(ARQUIVO_ACESSO_REMOTO.read_text(encoding='utf-8'))
                expiracao = datetime.fromisoformat(dados['expira_em'])
                if datetime.now().astimezone() < expiracao:
                    continue

                registrar_launcher('Token expirado; encerrando acesso remoto.')
                encerrar_cloudflare('expiração do token')
                ARQUIVO_ACESSO_REMOTO.unlink(missing_ok=True)
                registrar_launcher('Token expirado removido.')
        except Exception as erro:
            registrar_launcher(f'Erro na expiração do token: {erro!r}')


class SAAEApi:
    def revogar_acesso_remoto(self):
        """Revoga o token e encerra o túnel somente a partir do painel local."""
        try:
            janela = getattr(self, '_window', None)
            endereco = janela.get_current_url() if janela is not None else None
            # A ponte Python não pode autorizar uma página externa que tenha
            # sido carregada na janela do aplicativo.
            from urllib.parse import urlsplit
            url = urlsplit(endereco or '')
            if (url.scheme != 'http' or url.hostname != HOST or
                    url.port != PORT or url.path != '/dashboard.php'):
                return {'sucesso': False, 'mensagem': 'Revogação permitida somente no painel local.'}

            with CLOUDFLARE_LOCK:
                # Se o encerramento falhar, não apague o registro: assim não
                # informamos uma revogação bem-sucedida com o túnel ativo.
                encerrar_cloudflare('revogação manual pelo painel local')
                ARQUIVO_ACESSO_REMOTO.unlink(missing_ok=True)
                registrar_launcher('Acesso remoto revogado manualmente; JSON removido.')
                return {'sucesso': True, 'mensagem': 'Acesso remoto revogado.'}
        except Exception as erro:
            registrar_launcher(f'Falha na revogação manual: {erro!r}')
            return {'sucesso': False, 'mensagem': 'Não foi possível revogar o acesso. Consulte o log do launcher.'}

    def autorizar_local(self):
        # Never hand the secret to a remotely navigated page.
        if self._window is None:
            raise RuntimeError('Janela local indisponível')
        current = self._window.get_current_url()
        if not current or not current.startswith(f'http://{HOST}:{PORT}/index.php'):
            raise RuntimeError('Autorização disponível somente na entrada local')
        if not LOGIN_LOCAL_SEGREDO:
            raise RuntimeError('Credencial local indisponível')
        return LOGIN_LOCAL_SEGREDO

    def iniciar_acesso_remoto(self):
        try:
            with CLOUDFLARE_LOCK:
                dados_ativos = consultar_token_ativo()

                if dados_ativos:
                    return {
                        'sucesso': True,
                        'ja_ativo': True,
                        'url': dados_ativos['url'],
                        'codigo': dados_ativos['codigo'],
                        'expira_em': dados_ativos['expira_em']
                    }

                url = iniciar_cloudflare()

                if not url:
                    return {
                        'sucesso': False,
                        'mensagem': 'Cloudflare iniciando. Aguarde alguns segundos.'
                    }

                dados = salvar_acesso_remoto(url)

                return {
                    'sucesso': True,
                    'ja_ativo': False,
                    'url': dados['url'],
                    'codigo': dados['codigo'],
                    'expira_em': dados['expira_em']
                }

        except Exception as erro:
            registrar_launcher(f'Erro no acesso remoto: {erro!r}')
            return {
                'sucesso': False,
                'mensagem': str(erro)
            }


def open_panel():
    splash.withdraw()
    splash.destroy()
    try:
        api = SAAEApi()
        window = webview.create_window(
            'SAAE | Painel de Comandos e Níveis',
            URL,
            width=1440,
            height=900,
            min_size=(900, 650),
            resizable=True,
            hidden=True,
            js_api=api
        )
        api._window = window
        def show_window():
            try:
                window.maximize()
            except Exception:
                pass
            window.show()

            # Prioriza o foco da janela na inicialização.
            for _ in range(4):
                if focus_panel_window():
                    break
                time.sleep(0.2)

            # Teste: liberar seleção nos elementos de texto após carregar a página.
            if window.events.loaded.wait(timeout=15):
                window.evaluate_js("""
                    document.body.style.userSelect = 'text';
                    document.body.style.webkitUserSelect = 'text';

                    document.querySelectorAll('p, span, h1, h2, h3, strong, small').forEach(el => {
                        el.style.setProperty('user-select', 'text', 'important');
                        el.style.setProperty('-webkit-user-select', 'text', 'important');
                    });
                """)
        webview.start(show_window)
    finally:
        stop_processes()


def close_splash():
    STOP_EVENT.set()
    stop_processes()
    splash.destroy()


splash = tk.Tk()
splash.title('SAAE | Painel de Comandos e Níveis')
splash.configure(bg='#071b30')
splash.resizable(False, False)
w, h = 800, 450
x = (splash.winfo_screenwidth() - w) // 2
y = (splash.winfo_screenheight() - h) // 2
splash.geometry(f'{w}x{h}+{x}+{y}')
splash.protocol('WM_DELETE_WINDOW', close_splash)

# Fundo preparado na proporção da janela, sem dependências externas.
# Manter a referência da imagem evita que o Tkinter a descarte.
FUNDO_LAUNCHER = APP_DIR / 'assets' / 'launcher_fundo.png'
if FUNDO_LAUNCHER.is_file():
    try:
        splash.fundo_imagem = tk.PhotoImage(file=str(FUNDO_LAUNCHER))
        fundo_label = tk.Label(splash, image=splash.fundo_imagem, borderwidth=0)
        fundo_label.place(x=0, y=0, width=w, height=h)
    except tk.TclError as erro:
        registrar_launcher(f'Imagem do launcher indisponível: {erro!r}')

# Elementos posicionados na área livre à esquerda da ilustração.
COR_FUNDO_TEXTO = '#061d34'
title_label = tk.Label(splash, text='Controle de Comandos e Níveis', bg=COR_FUNDO_TEXTO,
                       fg='#e8f0fa', font=('Segoe UI', 20, 'bold'))
title_label.place(x=34, y=91)
subtitle_label = tk.Label(splash, text='Inicializando sistema de monitoramento',
                          bg=COR_FUNDO_TEXTO, fg='#a8c5dd', font=('Segoe UI', 10))
subtitle_label.place(x=36, y=137)
status_label = tk.Label(splash, text='Preparando inicialização...',
                        bg=COR_FUNDO_TEXTO, fg='#38bdf8', font=('Segoe UI', 10),
                        wraplength=355, justify='left', anchor='w')
status_label.place(x=36, y=244, width=355, height=52)
style = ttk.Style()
style.theme_use('clam')
style.configure('SAAE.Horizontal.TProgressbar', troughcolor='#1e293b',
                background='#38bdf8', bordercolor='#1e293b',
                lightcolor='#38bdf8', darkcolor='#38bdf8')
progress = ttk.Progressbar(splash, orient='horizontal', length=350, maximum=100,
                           style='SAAE.Horizontal.TProgressbar')
progress.place(x=36, y=309, width=350, height=15)
percent_label = tk.Label(splash, text='0%', bg=COR_FUNDO_TEXTO,
                         fg='#c2d6e7', font=('Segoe UI', 10))
percent_label.place(x=36, y=333)
retry_button = tk.Button(splash, text='Fechar', command=close_splash,
                         bg='#1b344d', fg='white', borderwidth=0, padx=20)
threading.Thread(target=startup, daemon=True).start()
splash.mainloop()
