@echo off
REM Envia a versao atual da pasta para o GitHub (branch main).
REM O Streamlit Cloud atualiza o app sozinho depois do envio.
cd /d "%~dp0"
git add -A
git commit -m "Atualizacao do app (%date%)"
REM traz antes o que foi feito direto no GitHub (ex.: Streamlit Cloud)
git pull --rebase --no-edit origin main
if errorlevel 1 (
  echo.
  echo *** Nao consegui juntar com o que esta no GitHub. Chame o Claude. ***
  git rebase --abort 2>nul
  pause
  exit /b 1
)
git push origin main
echo.
echo Pronto. Pode fechar esta janela.
pause
