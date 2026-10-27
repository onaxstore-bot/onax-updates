"""Install an isolated development beta; never overwrite an existing installation."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class InstallError(ValueError):
    pass


def install_beta(source, root, probe=None):
    source, root = Path(source).resolve(), Path(root).absolute()
    if not source.is_dir() or not (source / 'release_health.py').is_file() or not (source / 'painel_beta.py').is_file():
        raise InstallError('Pacote incompleto.')
    if root.exists() or root.is_symlink():
        raise InstallError('Instalação beta existente preservada.')
    if source == root.resolve() or root.resolve() in source.parents or source in root.resolve().parents:
        raise InstallError('A origem e o destino precisam ser separados.')
    root.parent.mkdir(parents=True, exist_ok=True)
    if probe is None:
        def probe(app):
            dependency = subprocess.run([sys.executable, '-I', '-c', 'import tkinter'], cwd=app,
                                        capture_output=True, timeout=15)
            if dependency.returncode:
                raise InstallError('Python sem suporte ao painel gráfico.')
            result = subprocess.run([sys.executable, '-I', str(app / 'release_health.py')], cwd=app,
                                    capture_output=True, timeout=45)
            if result.returncode:
                raise InstallError('Verificação do pacote falhou.')
    with tempfile.TemporaryDirectory(prefix='.techminer-beta-', dir=root.parent) as tmp:
        stage = Path(tmp) / 'stage'
        app = stage / 'app'
        app.mkdir(parents=True)
        # The beta contains code, tests and empty sample JSON only, never a credential directory.
        for item in source.rglob('*'):
            relative = item.relative_to(source)
            if item.is_symlink():
                raise InstallError('Links no pacote não são permitidos.')
            if item.is_dir() or '__pycache__' in relative.parts:
                continue
            if item.suffix not in ('.py', '.json', '.md') or any(part.startswith('.') for part in relative.parts):
                raise InstallError('Arquivo não permitido no pacote.')
            target = app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
        probe(app)
        # Atomic directory creation refuses an installation that appears while staging.
        try:
            root.mkdir()
        except FileExistsError:
            raise InstallError('Instalação beta existente preservada.') from None
        # On a disk error after this point, leave the incomplete beta for inspection;
        # never delete a directory another process could have written to.
        app.rename(root / 'app')
        (root / 'data').mkdir()
        # Use the same Python installation that passed the probe, not whichever pyw is on PATH.
        pythonw = str(Path(sys.executable).with_name('pythonw.exe'))
        if any(c in pythonw for c in '\r\n"'):
            raise InstallError('Caminho do Python inválido.')
        pythonw = pythonw.replace('%', '%%')
        (root / 'Abrir-TechMiner-Beta.cmd').write_text(
            '@echo off\nchcp 65001 >nul\nstart "" "' + pythonw + '" "%~dp0app\\painel_beta.py"\n', encoding='utf-8')
    return root


def main():
    if os.name != 'nt':
        print('Este protótipo de instalador é para Windows.')
        return 1
    if sys.version_info < (3, 10):
        print('É necessário Python 3.10 ou superior.')
        return 1
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        print('Não foi possível localizar a pasta de usuário.')
        return 1
    root = Path(local) / 'TechMiner-ONAX-Beta'
    try:
        executable = Path(sys.executable).with_name('pythonw.exe')
        if not executable.is_file():
            print('Python sem modo gráfico. Nenhuma instalação foi realizada.')
            return 1
        install_beta(Path(__file__).resolve().parent / 'app', root)
        subprocess.Popen([str(executable), str(root / 'app' / 'painel_beta.py')], close_fds=True)
        print('Beta instalado em pasta separada. Configure e teste o monitor no painel.')
        return 0
    except (OSError, InstallError, subprocess.TimeoutExpired):
        print('Instalação beta não concluída. Instalações existentes foram preservadas.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
