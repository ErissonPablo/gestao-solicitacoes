@echo off
REM Libera a porta 8520 no Firewall do Windows para acesso na rede local.
REM Precisa de admin: este script se auto-eleva.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Solicitando privilegios de administrador...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)
echo Criando regra de firewall para a porta 8520...
powershell -NoProfile -Command ^
  "Remove-NetFirewallRule -DisplayName 'Gestao SC Streamlit' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'Gestao SC Streamlit' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8520 -Profile Domain,Private | Out-Null"
echo.
echo Pronto! Porta 8520 liberada para a rede local (perfis Dominio e Privada).
echo Os colegas ja podem acessar enquanto o app estiver rodando.
pause
