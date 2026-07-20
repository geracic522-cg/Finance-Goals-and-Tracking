"""
Standalone launcher for the PyInstaller-bundled "Family Goals" dashboard.
This IS the .exe entrypoint -- it starts Streamlit's own server
programmatically (the same mechanism `streamlit run` uses under the hood)
and points it at the bundled Home.py.

NOT meant to be run directly during normal development -- use
`streamlit run Home.py` for that, same as always. This file only matters
when building the .exe.
"""

import os
import sys


def get_bundle_dir():
    """Where the bundled app SOURCE FILES (Home.py, pages/, db.py, etc.)
    live. When frozen by PyInstaller this is a temporary extraction
    folder (sys._MEIPASS) that's created fresh on every launch and
    deleted on exit. When run as a plain script, it's just this file's
    own directory."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_exe_dir():
    """Where the .exe (or this script) actually sits on disk -- this is
    where demo_finances.db is expected to live alongside it, so the
    database can be swapped or refreshed without rebuilding the
    executable. Deliberately NOT the same as get_bundle_dir(): that temp
    folder vanishes when the app closes, so a database placed there
    would be gone the next run."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def ensure_streamlit_credentials():
    """Streamlit prompts interactively for an email address on its very
    first run on a machine, waiting on stdin for input that will never
    come from a double-clicked .exe -- it would hang forever with no
    visible error. Setting STREAMLIT_BROWSER_GATHER_USAGE_STATS alone
    does NOT skip this specific prompt; pre-writing an empty credentials
    file does, since Streamlit only prompts when this file is absent."""
    config_dir = os.path.join(os.path.expanduser("~"), ".streamlit")
    os.makedirs(config_dir, exist_ok=True)
    credentials_path = os.path.join(config_dir, "credentials.toml")
    if not os.path.exists(credentials_path):
        with open(credentials_path, "w") as f:
            f.write('[general]\nemail = ""\n')


if __name__ == "__main__":
    bundle_dir = get_bundle_dir()
    exe_dir = get_exe_dir()

    # db.py looks up "demo_finances.db" as a relative path, so the
    # working directory needs to be wherever the .exe (and the .db file
    # sitting beside it on the thumb drive) actually live.
    os.chdir(exe_dir)

    ensure_streamlit_credentials()

    # Keep Streamlit quiet and non-interactive for a demo -- no telemetry
    # prompt, no "Welcome to Streamlit" email prompt on first run.
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

    from streamlit.web import cli as stcli

    home_path = os.path.join(bundle_dir, "Home.py")
    sys.argv = [
        "streamlit", "run", home_path,
        "--global.developmentMode=false",
        "--server.headless=false",
    ]
    sys.exit(stcli.main())
