"""PHANTOM launcher.

Keeps the old entrypoint working while the application lives in src/phantom.
"""
import os
import sys
import time
import traceback


_OUTPUT_HANDLES = []


def _redirect_output_for_gui_launch():
    if os.environ.get("PHANTOM_GUI_LAUNCH") != "1":
        return
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(log_dir, f"phantom_stdout_{stamp}.log")
    err_path = os.path.join(log_dir, f"phantom_stderr_{stamp}.log")
    stdout = open(out_path, "a", encoding="utf-8", buffering=1)
    stderr = open(err_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = stdout
    sys.stderr = stderr
    _OUTPUT_HANDLES.extend((stdout, stderr))


_redirect_output_for_gui_launch()

try:
    from src.phantom.app.main import main
except Exception:
    traceback.print_exc()
    raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
