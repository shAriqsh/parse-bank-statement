from pathlib import Path

import streamlit.web.bootstrap as bootstrap


def launch_ui(port: int = 8501, host: str = "localhost") -> int:
    """Launch the Streamlit audit inspector application and open the browser.

    Args:
        port: Port number for the Streamlit web server (default: 8501).
        host: Address to bind the Streamlit web server to (default: localhost).

    Returns:
        Exit code (0 on normal termination).
    """
    app_path = Path(__file__).resolve().parent / "app.py"
    flag_options = {
        "server.port": port,
        "server.address": host,
        "server.headless": False,
        "browser.gatherUsageStats": False,
    }
    bootstrap.run(
        str(app_path),
        is_hello=False,
        args=[],
        flag_options=flag_options,
    )
    return 0
