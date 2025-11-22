@echo off
cd /d %~dp0
venv\Scripts\activate
streamlit run app.py
