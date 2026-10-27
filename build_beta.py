"""Build a local-only beta installer archive, without credentials or store reports."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
LAUNCHER = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 ou superior e Python Launcher sao necessarios.
  pause
  exit /b 1
)
py -3 beta_setup.py
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Instalacao nao concluida. Verifique o Python e a pasta beta existente.
pause
exit /b %RESULT%
'''
README = '''TECHMINER ONAX — BETA DE MONITORAMENTO

Esta versao requer Python 3.10 ou superior, com tkinter e Python Launcher no Windows.
Execute INSTALAR-BETA.cmd apos extrair o ZIP. O beta cria uma pasta separada em
LOCALAPPDATA e recusa substituir uma instalacao beta existente. E somente leitura;
nao publica produtos, altera precos, compra ou paga pedidos. Credenciais devem ser
configuradas no proprio Windows e nao estao incluidas. A conexao direta, o fluxo
comercial e o atualizador ainda nao foram validados neste pacote. Nao e a versao final.
'''


def build(output):
    output = Path(output)
    source = ROOT / 'app'
    required = [ROOT / 'beta_setup.py', source / 'release_health.py', source / 'painel_beta.py']
    if any(not p.is_file() or p.is_symlink() for p in required):
        raise ValueError('Fontes ausentes ou inválidas.')
    files = []
    empty_samples = {'pre_catalogo.json': {'items': []}, 'pesquisa_multiplataforma.json': {'offers': []},
                     'shopify_snapshot.json': {'data': {}}}
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError('Links não são permitidos.')
        if path.is_dir() or '__pycache__' in relative.parts:
            continue
        if path.suffix not in ('.py', '.json', '.md') or any(part.startswith('.') for part in relative.parts):
            raise ValueError('Arquivo não permitido na distribuição.')
        if path.suffix == '.json':
            if relative.as_posix() not in empty_samples or json.loads(path.read_text(encoding='utf-8')) != empty_samples[relative.as_posix()]:
                raise ValueError('Dados não permitidos na distribuição.')
        files.append((path, 'app/' + relative.as_posix()))
    with ZipFile(output, 'x', ZIP_DEFLATED) as archive:
        archive.write(ROOT / 'beta_setup.py', 'beta_setup.py')
        archive.writestr('INSTALAR-BETA.cmd', LAUNCHER)
        archive.writestr('LEIA-ME.txt', README)
        for path, name in sorted(files, key=lambda item: item[1]):
            archive.write(path, name)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('saida', type=Path)
    args = parser.parse_args()
    print('Beta criado:', build(args.saida))
