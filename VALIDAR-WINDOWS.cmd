@echo off
setlocal
cd /d "%~dp0"
:logname
set "LOG=%TEMP%\TechMiner-validacao-%RANDOM%-%RANDOM%.txt"
if exist "%LOG%" goto logname
echo TechMiner ONAX - verificacao local Windows > "%LOG%"
where py >nul 2>&1
if errorlevel 1 goto sempython
py -3 --version >> "%LOG%" 2>&1
if errorlevel 1 goto erro
py -3 app\release_health.py >> "%LOG%" 2>&1
if errorlevel 1 goto erro
py -3 -m unittest test_beta_setup test_windows_integration -v >> "%LOG%" 2>&1
if errorlevel 1 goto erro
echo RESULTADO: testes locais concluidos. >> "%LOG%"
echo RESULTADO: testes locais concluidos.
echo Isso nao valida conexoes reais, agendamento, notificacoes ou instalador final.
echo Relatorio: "%LOG%"
pause
exit /b 0
:sempython
echo Python Launcher nao localizado. Nenhuma instalacao foi feita. >> "%LOG%"
:erro
echo RESULTADO: validacao nao concluida. >> "%LOG%"
echo Validacao nao concluida. Consulte "%LOG%".
pause
exit /b 1
