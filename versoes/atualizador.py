"""Atualizador SAAE Painel - executar com Python 3, sem dependencias extras.
Teste em uma copia do projeto. Nao implementa assinatura digital.
"""
import ctypes
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.request
import zipfile
import urllib.error

BASE = Path(__file__).resolve().parent
REPO = 'samuelrochacarvalho/SAAE_PAINEL'
VERSAO_URL = f'https://raw.githubusercontent.com/{REPO}/main/versao.json'
ZIP_URL = f'https://codeload.github.com/{REPO}/zip/refs/heads/main'
VERSAO_ALTERNATIVA = f'https://github.com/{REPO}/raw/refs/heads/main/versao.json'
MAX_ZIP = 40 * 1024 * 1024
MAX_FILE = 15 * 1024 * 1024
MAX_TOTAL = 80 * 1024 * 1024
PROTECTED_FILES = {'.gitignore', 'atualizador.py', 'mqtt/config.py', 'config/comandos.php'}
PROTECTED_DIRS = ('.git/', 'dados/', 'runtime/', 'config/', '__pycache__/', '.venv/', 'venv/')
ALLOWED_DIRS = ('api/', 'assets/', 'mqtt/')
ALLOWED_FILES = {'launcher.pyw', 'launcher.py', 'index.php'}


def request_bytes(url, limit=MAX_ZIP):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'SAAE-Painel-Atualizador/1.0',
        'Accept': '*/*',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        chunks, total = [], 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError('Download excedeu o limite de tamanho.')
            chunks.append(chunk)
    return b''.join(chunks)


def parse_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Versao invalida no versao.json.')
    return tuple(map(int, value.split('.')))


def read_local_version():
    path = BASE / 'versao.json'
    if not path.is_file():
        raise FileNotFoundError('versao.json local nao encontrado.')
    return json.loads(path.read_text(encoding='utf-8-sig'))['versao']


def wait_for_parent(pid):
    if not pid or os.name != 'nt':
        return
    SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
    if handle:
        try:
            result = kernel32.WaitForSingleObject(handle, 30000)
            if result == 0x102:
                raise TimeoutError('O launcher nao encerrou em 30 segundos.')
        finally:
            kernel32.CloseHandle(handle)


def permitted(relative):
    if relative in PROTECTED_FILES or any(relative.startswith(p) for p in PROTECTED_DIRS):
        return False
    if relative in ALLOWED_FILES:
        return True
    return any(relative.startswith(p) for p in ALLOWED_DIRS) and not relative.startswith('mqtt/config.py')


def extract_plan(archive, expected_version):
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        entries = zf.infolist()
        if len(entries) > 2000:
            raise ValueError('Pacote com arquivos demais.')
        files, total = {}, 0
        for entry in entries:
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if len(parts) < 2 or any(p in ('', '.', '..') for p in parts):
                raise ValueError('Caminho invalido no ZIP.')
            rel = '/'.join(parts[1:])
            if not rel or '\\' in rel or ':' in rel or rel.startswith('/'):
                raise ValueError('Caminho inseguro no ZIP.')
            # Impede links simbolicos Unix.
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Link simbolico nao permitido.')
            if entry.file_size > MAX_FILE:
                raise ValueError('Arquivo grande demais: ' + rel)
            total += entry.file_size
            if total > MAX_TOTAL:
                raise ValueError('Pacote descompactado excede o limite.')
            if rel == 'versao.json' or permitted(rel):
                if rel in files:
                    raise ValueError('Arquivo duplicado: ' + rel)
                files[rel] = zf.read(entry)
        if 'versao.json' not in files:
            raise ValueError('Pacote nao contem versao.json.')
        manifest = json.loads(files['versao.json'].decode('utf-8-sig'))
        if manifest.get('versao') != expected_version:
            raise ValueError('Versao do pacote difere da versao consultada.')
        if 'launcher.pyw' not in files or 'index.php' not in files:
            raise ValueError('Pacote incompleto: launcher.pyw ou index.php ausente.')
        if len(files) < 3:
            raise ValueError('Nenhum arquivo de sistema encontrado.')
        return files


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.saae-novo')
    try:
        with tmp.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class Updater:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('SAAE | Atualizador')
        self.root.configure(bg='#0b1220')
        self.root.geometry('640x290')
        self.root.resizable(False, False)
        tk.Label(self.root, text='SAAE | ATUALIZADOR', font=('Segoe UI', 20, 'bold'),
                 bg='#0b1220', fg='#e8f0fa').pack(pady=(25, 10))
        self.status = tk.Label(self.root, text='Preparando...', font=('Segoe UI', 11),
                               bg='#0b1220', fg='#38bdf8', wraplength=590)
        self.status.pack(pady=12)
        self.progress = ttk.Progressbar(self.root, length=540, maximum=100)
        self.progress.pack(pady=8)
        self.details = tk.Label(self.root, text='', bg='#0b1220', fg='#94a3b8',
                                font=('Segoe UI', 10), wraplength=590)
        self.details.pack(pady=10)
        self.close = tk.Button(self.root, text='Fechar', command=self.root.destroy,
                               bg='#1b344d', fg='white', padx=20, state='disabled')
        self.close.pack(pady=8)
        self.root.protocol('WM_DELETE_WINDOW', lambda: None)
        self.parent_pid = self.parse_parent_pid()
        threading.Thread(target=self.run, daemon=True).start()

    @staticmethod
    def parse_parent_pid():
        if len(sys.argv) == 3 and sys.argv[1] == '--parent-pid':
            return int(sys.argv[2])
        return None

    def show(self, message, percent, details=None):
        def apply():
            self.status.config(text=message)
            self.progress['value'] = percent
            if details is not None:
                self.details.config(text=details)
        self.root.after(0, apply)

    def finish(self, success, message):
        def apply():
            self.status.config(text=message, fg='#4ade80' if success else '#f87171')
            self.close.config(state='normal')
            self.root.protocol('WM_DELETE_WINDOW', self.root.destroy)
        self.root.after(0, apply)

    def consultar_versao_remota(self):
        """Consulta dois enderecos publicos sem API e escolhe a versao mais nova."""
        versoes = []
        erros = []
        for origem in (VERSAO_URL, VERSAO_ALTERNATIVA):
            url = origem + '?saae_cache=' + str(time.time_ns())
            try:
                dados = json.loads(request_bytes(url, 100_000))
                versao = dados['versao']
                parse_version(versao)
                versoes.append(versao)
            except Exception as erro:
                erros.append(f'{origem}: {erro}')
        if not versoes:
            raise RuntimeError('Nao foi possivel consultar a versao no GitHub: ' + '; '.join(erros))
        return max(versoes, key=parse_version)

    def run(self):
        changed = False
        try:
            self.show('Verificando versao instalada...', 5)
            local = read_local_version()
            parse_version(local)
            self.show('Consultando versao publica do GitHub...', 12)
            remote = self.consultar_versao_remota()
            self.show('Versoes consultadas.', 20, f'Local: {local}  |  GitHub: {remote}')
            if parse_version(remote) <= parse_version(local):
                self.show('Sistema ja atualizado.', 100)
                self.finish(True, 'Nenhuma atualizacao necessaria.')
                return

            # O ZIP de main pode ficar atrasado em relacao ao arquivo Raw.
            # Tentar novamente sem alterar arquivos ate obter versoes iguais.
            files = None
            for tentativa in range(1, 4):
                self.show(f'Baixando pacote (tentativa {tentativa}/3)...', 30)
                zip_url = ZIP_URL + '?saae_cache=' + str(time.time_ns())
                archive = request_bytes(zip_url)
                self.show('Validando versao e estrutura do pacote...', 55)
                try:
                    files = extract_plan(archive, remote)
                    break
                except ValueError as erro:
                    if 'Versao do pacote difere' not in str(erro):
                        raise
                    if tentativa == 3:
                        raise RuntimeError(
                            f'O ZIP do GitHub ainda nao corresponde a versao {remote}. '
                            'Aguarde a sincronizacao e tente novamente.'
                        ) from erro
                    self.show('GitHub ainda sincronizando o ZIP; aguardando...', 45)
                    time.sleep(3)

            self.show('Aguardando encerramento do launcher...', 65)
            wait_for_parent(self.parent_pid)
            changes = [(name, data) for name, data in files.items() if name != 'versao.json']
            changes.sort(key=lambda item: item[0])
            for index, (name, data) in enumerate(changes, 1):
                self.show(f'Instalando: {name}', 65 + int(28 * index / len(changes)),
                          f'{index} de {len(changes)} arquivos')
                changed = True
                atomic_write(BASE / Path(name), data)
            atomic_write(BASE / 'versao.json', files['versao.json'])
            self.show('Atualizacao concluida.', 100, f'Versao instalada: {remote}')
            self.root.after(0, lambda: self.countdown(5))
        except Exception as error:
            extra = (' Instalacao pode estar parcial; nao reinicie automaticamente.'
                     if changed else ' Nenhum arquivo foi substituido.')
            self.finish(False, f'Falha: {error}.{extra}')

    def countdown(self, seconds):
        # Agendado na thread do Tkinter; sem bloquear a janela.
        if seconds > 0:
            self.status.config(text='Atualizacao concluida com sucesso!', fg='#4ade80')
            self.details.config(text=f'Abrindo SAAE Painel em {seconds} segundo(s)...')
            self.close.config(state='disabled')
            self.root.after(1000, lambda: self.countdown(seconds - 1))
        else:
            self.details.config(text='Iniciando launcher.pyw...')
            self.restart_launcher()

    def restart_launcher(self):
        try:
            if os.name == 'nt':
                python = Path(sys.executable)
                pythonw = python.with_name('pythonw.exe')
                if pythonw.is_file():
                    python = pythonw
                subprocess.Popen([str(python), str(BASE / 'launcher.pyw')],
                                 cwd=str(BASE), creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([sys.executable, str(BASE / 'launcher.pyw')], cwd=str(BASE))
            self.root.destroy()
        except Exception as error:
            self.finish(False, f'Atualizado, mas nao foi possivel reiniciar: {error}')


if __name__ == '__main__':
    Updater().root.mainloop()
