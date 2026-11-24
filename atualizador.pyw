"""Atualizador SAAE Painel - executar com Python 3, sem dependencias extras.
Teste em uma copia do projeto. Nao implementa assinatura digital.
"""
import ctypes
import io
import shutil
import tempfile
import stat
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
MAX_ZIP = 150 * 1024 * 1024
MAX_FILE = 70 * 1024 * 1024
MAX_TOTAL = 200 * 1024 * 1024
PROTECTED_FILES = {'atualizador.pyw', 'mqtt/config.py', 'config/comandos.php', 'atenção.txt'}
PROTECTED_DIRS = {'.git', 'dados', 'runtime', 'dependencias', 'logs', '__pycache__', '.venv', 'venv'}
REQUIRED = {'launcher.pyw', 'index.php', 'versao.json'}


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
    parts = relative.casefold().split('/')
    return not any(relative.casefold() == p or relative.casefold().startswith(p + '/') for p in PROTECTED_FILES) and not any(
        part in PROTECTED_DIRS for part in parts)


def safe_parts(name):
    parts = name.rstrip('/').split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part.endswith(('.', ' '))
                or re.search(r'[\\:<>"|?*\x00-\x1f]', part)
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', part.split('.')[0])):
            raise ValueError('Caminho inseguro no ZIP: ' + name)
    return parts


def extract_plan(archive, expected_version):
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        entries = zf.infolist()
        if len(entries) > 2000:
            raise ValueError('Pacote com arquivos demais.')
        files, total, seen, roots = {}, 0, set(), set()
        for entry in entries:
            parts = safe_parts(entry.filename)
            roots.add(parts[0])
            if entry.is_dir():
                continue
            if len(parts) < 2:
                raise ValueError('Estrutura invalida no ZIP.')
            rel = '/'.join(parts[1:])
            if not permitted(rel):
                continue
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Link simbolico nao permitido.')
            key = rel.casefold()
            if key in seen:
                raise ValueError('Arquivo duplicado: ' + rel)
            seen.add(key)
            if entry.file_size > MAX_FILE:
                raise ValueError('Arquivo grande demais: ' + rel)
            total += entry.file_size
            if total > MAX_TOTAL:
                raise ValueError('Pacote descompactado excede o limite.')
            data = zf.read(entry)
            # GitHub ZIP entrega o conteudo do Git, sem conversao de checkout.
            # Normaliza scripts Windows antes da instalacao e da validacao.
            if PurePosixPath(rel).suffix.lower() in ('.bat', '.cmd'):
                data = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
            files[rel] = data
        if len(roots) != 1 or not REQUIRED <= files.keys():
            raise ValueError('Pacote incompleto ou estrutura invalida.')
        for key in seen:
            parts = key.split('/')
            if any('/'.join(parts[:i]) in seen for i in range(1, len(parts))):
                raise ValueError('Conflito entre arquivo e pasta.')
        manifest = json.loads(files['versao.json'].decode('utf-8-sig'))
        if manifest.get('versao') != expected_version:
            raise ValueError('Versao do pacote difere da versao consultada.')
        return files


def check_link(path):
    st = path.lstat()
    if path.is_symlink() or getattr(st, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Link ou junction nao permitido: ' + str(path))


def local_files(base):
    result = []
    def visit(folder):
        for path in folder.iterdir():
            rel = path.relative_to(base).as_posix()
            if not permitted(rel):
                continue
            check_link(path)
            if path.is_dir():
                visit(path)
            elif path.is_file():
                result.append(rel)
            else:
                raise ValueError('Arquivo local especial: ' + rel)
    visit(base)
    return result


def clean_update(base, files, notify):
    # Backup fora da raiz servida pelo PHP. Nao inclui dados protegidos.
    backup = Path(tempfile.mkdtemp(prefix='SAAE_backup_', dir=base.parent))
    old = local_files(base)
    written = []
    removed = []
    try:
        for name in old:
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / name, dest)
        notify('Backup concluido. Renovando arquivos...', 72)
        for name in old:
            if name == 'versao.json':
                continue
            (base / name).unlink()
            removed.append(name)
        # Pastas vazias podem permanecer; nenhum arquivo obsoleto permanece.
        changes = sorted(name for name in files if name != 'versao.json')
        for index, name in enumerate(changes, 1):
            notify('Instalando: ' + name, 73 + int(22 * index / len(changes)))
            atomic_write(base / name, files[name])
            written.append(name)
        for name in changes:
            if (base / name).read_bytes() != files[name]:
                raise IOError('Validacao falhou: ' + name)
        atomic_write(base / 'versao.json', files['versao.json'])
        written.append('versao.json')
    except Exception as error:
        try:
            for name in reversed(written):
                (base / name).unlink(missing_ok=True)
            for name in set(removed + written) & set(old):
                atomic_write(base / name, (backup / name).read_bytes())
        except Exception as restore_error:
            raise RuntimeError(f'Falha na restauracao: {restore_error}. Backup: {backup}') from error
        raise RuntimeError(f'Atualizacao cancelada; arquivos anteriores preservados ou restaurados. Backup: {backup}. {error}') from error
    else:
        shutil.rmtree(backup, ignore_errors=True)


def atomic_write(path, data):
    for parent in path.parents:
        if parent.exists():
            check_link(parent)
    if path.exists():
        check_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.saae-novo-', dir=path.parent)
    os.close(fd)
    tmp = Path(temp_name)
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
        # Centraliza e traz a janela do atualizador para frente
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.focus_force()

        # Remove o modo "sempre no topo" após 1,5 segundo
        self.root.after(
            1500,
            lambda: self.root.attributes('-topmost', False)
        )
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
            changed = True
            clean_update(BASE, files, self.show)
            self.show('Atualizacao concluida.', 100, f'Versao instalada: {remote}')
            self.root.after(0, lambda: self.countdown(5))
        except Exception as error:
            extra = (' Confira a mensagem de recuperacao antes de reiniciar.'
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
