@echo off
REM Envia a versao atual da pasta para o GitHub (branch main).
REM O Streamlit Cloud atualiza o app sozinho depois do envio.
cd /d "%~dp0"
git add -A
git commit -m "Atualizacao do app (%date%)"
git push origin main
echo.
echo Pronto. Pode fechar esta janela.
pause
