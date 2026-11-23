@echo off
title Painel - Missao em Cortes
REM Coloque este arquivo na raiz do repo (ao lado do pyproject.toml).
cd /d "%~dp0"

REM Painel ja esta rodando? So abre o navegador.
netstat -ano | findstr ":8501" | findstr "LISTENING" >nul
if %errorlevel%==0 goto abrir

where uv >nul 2>&1 || (echo [ERRO] uv nao encontrado no PATH. & pause & exit /b 1)

echo Subindo o painel...
start "Painel (servidor) - nao feche" /min cmd /k "uv run streamlit run painel/app.py"

REM Espera o servidor responder (ate ~60s)
set /a tentativas=0
:esperar
timeout /t 1 /nobreak >nul
set /a tentativas+=1
netstat -ano | findstr ":8501" | findstr "LISTENING" >nul
if %errorlevel%==0 goto abrir
if %tentativas% geq 60 (echo [ERRO] O painel nao subiu. Veja a janela minimizada "Painel (servidor)". & pause & exit /b 1)
goto esperar

:abrir
start "" http://localhost:8501
exit /b 0