"""Prepare or register a per-user Windows task; never stores credentials in task XML."""
import argparse
import csv
import io
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


TASK_NAME = 'TechMiner-ONAX-Beta-Monitor'
NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def child(parent, name, value=None, **attributes):
    item = ET.SubElement(parent, '{%s}%s' % (NS, name), attributes)
    if value is not None:
        item.text = str(value)
    return item


def build_xml(*, sid, executable, job, directory, vault, cj_shop, domain):
    if not isinstance(sid, str) or not re.fullmatch(r'S-1-(?:\d+-)*\d+', sid):
        raise ValueError('SID inválido.')
    if not isinstance(cj_shop, str) or not cj_shop.isascii() or not cj_shop.isdigit():
        raise ValueError('Loja CJ inválida.')
    if not isinstance(domain, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com', domain):
        raise ValueError('Domínio inválido.')
    paths = [str(executable), str(job), str(directory), str(vault)]
    if any(not p or '"' in p or any(ord(c) < 32 for c in p) for p in paths):
        raise ValueError('Caminho inválido.')
    task = ET.Element('{%s}Task' % NS, {'version': '1.2'})
    triggers = child(task, 'Triggers')
    calendar = child(triggers, 'CalendarTrigger')
    child(calendar, 'StartBoundary', '2026-01-01T08:00:00')
    child(calendar, 'Enabled', 'true')
    daily = child(calendar, 'ScheduleByDay')
    child(daily, 'DaysInterval', '1')
    logon = child(triggers, 'LogonTrigger')
    child(logon, 'Enabled', 'true')
    child(logon, 'UserId', sid)
    principals = child(task, 'Principals')
    principal = child(principals, 'Principal', id='Author')
    child(principal, 'UserId', sid)
    child(principal, 'LogonType', 'InteractiveToken')
    child(principal, 'RunLevel', 'LeastPrivilege')
    settings = child(task, 'Settings')
    for name, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                        ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'true'),
                        ('ExecutionTimeLimit', 'PT30M')]:
        child(settings, name, value)
    actions = child(task, 'Actions', Context='Author')
    execute = child(actions, 'Exec')
    child(execute, 'Command', paths[0])
    args = [paths[1], '--dados', paths[2], '--cofre', paths[3], '--loja-cj', cj_shop, '--dominio', domain]
    child(execute, 'Arguments', subprocess.list2cmdline(args))
    child(execute, 'WorkingDirectory', str(Path(paths[1]).parent))
    return ET.tostring(task, encoding='utf-16', xml_declaration=True)


def current_sid():
    result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, timeout=10)
    row = next(csv.reader(io.StringIO(result.stdout)), [])
    if result.returncode or not row:
        raise ValueError('Usuário Windows não identificado.')
    return row[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Registrar monitor local no Agendador de Tarefas.')
    parser.add_argument('--dados', required=True, type=Path)
    parser.add_argument('--cofre', required=True, type=Path)
    parser.add_argument('--loja-cj', required=True)
    parser.add_argument('--dominio', default='example.myshopify.com')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('Agendamento disponível somente no Windows.')
        return 1
    try:
        job = Path(__file__).with_name('job_monitor.py').resolve()
        executable = Path(sys.executable).with_name('pythonw.exe').resolve()
        if not executable.is_file() or not job.is_file() or not args.cofre.is_file():
            raise ValueError('Arquivos necessários indisponíveis.')
        data = build_xml(sid=current_sid(), executable=executable, job=job,
                         directory=args.dados.resolve(), vault=args.cofre.resolve(),
                         cj_shop=args.loja_cj, domain=args.dominio)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'task.xml'
            path.write_bytes(data)
            # No /F: preserve an existing task instead of silently replacing it.
            result = subprocess.run(['schtasks.exe', '/Create', '/TN', TASK_NAME, '/XML', str(path)],
                                    capture_output=True, stdin=subprocess.DEVNULL, timeout=20)
        if result.returncode:
            raise ValueError('Agendamento recusado.')
        print('Tarefa criada. Valide a próxima execução no Agendador e no monitor.')
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print('Agendamento não concluído; tarefas existentes foram preservadas.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
