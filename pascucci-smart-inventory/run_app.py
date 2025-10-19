import sys
from streamlit.web import cli as stcli

if __name__ == "__main__":
    sys.argv = ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
    stcli.main()
