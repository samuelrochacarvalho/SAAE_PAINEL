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

import webview

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
PHP_EXE = APP_DIR / 'runtime' / 'php' / 'php.exe'
DB_FILE = APP_DIR / 'dados' / 'saae.db'
MQTT_SCRIPT = APP_DIR / 'mqtt' / 'cliente.py'
INDEX_FILE = APP_DIR / 'index.php'
HOST = '127.0.0.1'
PORT = 8090
URL = f'http://{HOST}:{PORT}/'

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
PROCS = []
WINDOW = None
STARTED = False
STOP_EVENT = threading.Event()
PROCS_LOCK = threading.RLock()
LOG_DIR = APP_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)


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
        with urllib.request.urlopen(URL, timeout=1.5) as r:
            return r.status == 200
    except Exception:
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
            retry_button.pack(pady=8)
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
    for path in (PHP_EXE, INDEX_FILE, MQTT_SCRIPT):
        if not path.is_file():
            raise FileNotFoundError(f'Arquivo não encontrado: {path.relative_to(APP_DIR)}')
    if not DB_FILE.is_file():
        raise FileNotFoundError('Banco SQLite não encontrado: dados/saae.db')
    with sqlite3.connect(f'file:{DB_FILE.as_posix()}?mode=ro', uri=True, timeout=5) as db:
        db.execute('SELECT 1 FROM estacao_heartbeat LIMIT 1').fetchone()


def startup():
    global STARTED
    try:
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

        # Somente detecta atualizações; não baixa nem altera arquivos nesta etapa.
        update_status('Verificando atualizações...', 22)
        atualizacao_disponivel = verificar_atualizacao()
        if STOP_EVENT.is_set():
            return
        if atualizacao_disponivel is True:
            update_status('Nova versão disponível! (instalação ainda não ativada)', 23)
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
        php_proc = start_process([str(PHP_EXE), '-S', f'{HOST}:{PORT}', '-t', str(APP_DIR)], APP_DIR)
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
        update_status('Abrindo Painel Supervisório SAAE...', 95)
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

    hwnd = user32.FindWindowW(None, 'SAAE | Painel Supervisório')
    if not hwnd:
        return False

    # Coloca momentaneamente à frente; não deixa o painel sempre no topo.
    flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # TOPMOST
    user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)  # NOTOPMOST
    return bool(user32.SetForegroundWindow(hwnd))


def open_panel():
    splash.withdraw()
    splash.destroy()
    try:
        window = webview.create_window('SAAE | Painel Supervisório', URL,
                                       width=1440, height=900,
                                       min_size=(900, 650), resizable=True,
                                       hidden=True)
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
splash.title('SAAE | Painel Supervisório')
splash.configure(bg='#0b1220')
splash.resizable(False, False)
w, h = 520, 300
x = (splash.winfo_screenwidth() - w) // 2
y = (splash.winfo_screenheight() - h) // 2
splash.geometry(f'{w}x{h}+{x}+{y}')
splash.protocol('WM_DELETE_WINDOW', close_splash)

title_label = tk.Label(splash, text='SAAE SUPERVISÓRIO', bg='#0b1220', fg='#e8f0fa',
                       font=('Segoe UI', 21, 'bold'))
title_label.pack(pady=(36, 8))
tk.Label(splash, text='Inicializando sistema de monitoramento', bg='#0b1220',
         fg='#94a3b8', font=('Segoe UI', 11)).pack(pady=(0, 22))
status_label = tk.Label(splash, text='Preparando inicialização...', bg='#0b1220',
                        fg='#38bdf8', font=('Segoe UI', 10), wraplength=460)
status_label.pack(pady=5)
style = ttk.Style()
style.theme_use('clam')
style.configure('SAAE.Horizontal.TProgressbar', troughcolor='#1e293b', background='#38bdf8',
                bordercolor='#1e293b', lightcolor='#38bdf8', darkcolor='#38bdf8')
progress = ttk.Progressbar(splash, orient='horizontal', length=410, maximum=100,
                           style='SAAE.Horizontal.TProgressbar')
progress.pack(pady=13)
percent_label = tk.Label(splash, text='0%', bg='#0b1220', fg='#94a3b8', font=('Segoe UI', 10))
percent_label.pack()
retry_button = tk.Button(splash, text='Fechar', command=close_splash,
                         bg='#1b344d', fg='white', borderwidth=0, padx=20)
threading.Thread(target=startup, daemon=True).start()
splash.mainloop()
