@echo off
REM Inicia a ferramenta de Gestao de Solicitacoes de Compra
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
streamlit run app.py
pause
