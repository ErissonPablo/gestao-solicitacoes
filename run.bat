@echo off
REM Inicia a ferramenta de Gestao de Solicitacoes de Compra
cd /d "%~dp0"
where streamlit >nul 2>nul || python -m pip install -r requirements.txt
streamlit run app.py
pause
