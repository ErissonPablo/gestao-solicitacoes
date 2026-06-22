@echo off
REM Sobe a ferramenta para acesso na REDE LOCAL (porta fixa 8520).
REM Deixe esta janela aberta enquanto os colegas estiverem usando.
cd /d "%~dp0"
where streamlit >nul 2>nul || python -m pip install -r requirements.txt

echo ============================================================
echo  Gestao de Solicitacoes de Compra - acesso pela rede local
echo ------------------------------------------------------------
echo  Compartilhe um destes enderecos com a equipe:
echo.
echo     http://LCO330:8520
echo     http://192.168.101.184:8520
echo.
echo  (o IP pode mudar; o nome LCO330 e mais estavel)
echo  Mantenha esta janela ABERTA e o PC ligado.
echo ============================================================
echo.
streamlit run app.py --server.port 8520 --server.address 0.0.0.0 --browser.gatherUsageStats false
pause
