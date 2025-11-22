import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

cmd = [venv_python, "-m", "streamlit", "run", os.path.join(BASE_DIR, "app.py")]
subprocess.Popen(cmd)
