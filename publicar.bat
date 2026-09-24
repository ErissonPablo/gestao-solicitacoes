@echo off
REM Envia a versao atual da pasta para o GitHub (branch main).
REM O Streamlit Cloud atualiza o app sozinho depois do envio.
cd /d "%~dp0"
git add -A
git commit -m "Dashboard novo: visao geral, alertas e backlog com Atendida / Onde encontrar"
git push origin main
echo.
echo Pronto. Pode fechar esta janela.
pause
