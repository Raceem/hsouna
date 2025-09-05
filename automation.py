# automation.py
import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------
# Force our own stdout to utf-8 too (helps if piping)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# Logging setup
LOG_DIR = Path.cwd() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "automation_runner.log"

logger = logging.getLogger("automation_runner")
logger.setLevel(logging.INFO)
logger.handlers.clear()

# Console
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))

# Rotating file
fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
    "%Y-%m-%d %H:%M:%S",
))

logger.addHandler(ch)
logger.addHandler(fh)

# ---------------------------------------------------------------------

CONFIG_PATH = Path(__file__).with_name("config.py")

# ===== Runner state (visible to Flask UI) =====================================

class _RunnerState:
    def __init__(self):
        self._lock = threading.Lock()
        self.running: bool = False
        self.current_step: str = ""
        self.cmdline: str = ""
        self.started_at: Optional[float] = None
        self.last_error: str = ""
        self.proc: Optional[subprocess.Popen] = None  # handle to current step

    def set_running(self, running: bool):
        with self._lock:
            self.running = running
            if running:
                self.started_at = time.time()
            else:
                self.proc = None
                self.current_step = ""
                self.cmdline = ""

    def set_step(self, step: str, cmdline: str = ""):
        with self._lock:
            self.current_step = step
            self.cmdline = cmdline

    def set_proc(self, proc: Optional[subprocess.Popen]):
        with self._lock:
            self.proc = proc

    def set_error(self, msg: str):
        with self._lock:
            self.last_error = msg

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "current_step": self.current_step,
                "cmdline": self.cmdline,
                "started_at": self.started_at,
                "last_error": self.last_error,
                "proc_alive": bool(self.proc and (self.proc.poll() is None)),
            }

_STATE = _RunnerState()

def get_status() -> dict:
    """Return a dict suitable for /status polling."""
    return _STATE.snapshot()

def cancel_current():
    """Terminate the current running subprocess (if any) and mark runner idle."""
    snap = _STATE.snapshot()
    if not snap["running"]:
        return False  # nothing to cancel

    proc = _STATE.proc
    if proc and proc.poll() is None:
        logger.warning("Cancelling current step: %s", snap["current_step"])
        try:
            proc.terminate()   # gentle
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()    # force
            except Exception:
                pass
    _STATE.set_running(False)
    _STATE.set_error("Cancelled by user")
    logger.info("Pipeline cancelled.")
    return True

# ===== File helpers ============================================================

def _read_text(p: Path) -> str:
    with p.open("r", encoding="utf-8") as f:
        return f.read()

def _write_text(p: Path, content: str) -> None:
    with p.open("w", encoding="utf-8") as f:
        f.write(content)

def update_config(folder_name: str, target_date: str, pdf_filename: str):
    """
    Update selected variables in config.py (inline).
    (HIJRI_DAY / PAYS no longer managed here.)
    """
    logger.info("Updating config.py at %s", CONFIG_PATH)
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.py not found at {CONFIG_PATH}")

    content = _read_text(CONFIG_PATH)

    replacements: Dict[str, str] = {
        "FOLDER_NAME": f'"{folder_name}"',
        "TARGET_DATE": f'"{target_date}"',
        "PDF_FILE": f'os.path.join(BASE_DIR, FOLDER_NAME, "{pdf_filename}")',
    }

    # Log existing values (best-effort read)
    for var in replacements.keys():
        m = re.search(rf"^{var}\s*=\s*(.+)$", content, flags=re.MULTILINE)
        if m:
            logger.info("config.py current %s = %s", var, m.group(1).strip())

    # Apply replacements
    for var, value in replacements.items():
        pattern = rf"^{var}\s*=.*$"
        new_line = f"{var} = {value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            # If not present, append
            content += f"\n{new_line}\n"
        logger.info("config.py set %s -> %s", var, value)

    _write_text(CONFIG_PATH, content)
    logger.info("config.py updated successfully.")

# ===== Subprocess runner =======================================================

def _run_child(cmd: list[str], log_prefix: str):
    """
    Internal: run a child process, stream logs, wire state so UI can cancel.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    logger.info("Launching: %s", " ".join(cmd))
    _STATE.set_step(log_prefix, " ".join(cmd))

    start = time.time()
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
        universal_newlines=True,
        env=env,
    ) as proc:
        _STATE.set_proc(proc)
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                logger.info("[%-18s] %s", log_prefix, line.rstrip())
        finally:
            ret = proc.wait()

    dur = time.time() - start
    if ret != 0:
        raise subprocess.CalledProcessError(ret, cmd, output=f"{log_prefix} failed ({dur:.2f}s)")
    logger.info("Step '%s' finished OK (%.2fs)", log_prefix, dur)

def run_step(script: str, description: str):
    """
    Run a child python script ONCE, streaming its stdout/stderr into our logger.
    Forces UTF-8 in the child interpreter (-X utf8) so emojis/non-ASCII won't crash.
    Makes the child process killable via cancel_current().
    """
    cmd = [sys.executable, "-X", "utf8", script]
    logger.info("=== %s ===", description)
    _run_child(cmd, script)

# ===== Pipeline (sync) & async wrapper ========================================

def run_pipeline(pdf: str, folder: str | None = None, target_date: str | None = None):
    """
    Run the full reservation pipeline (synchronous).
    UI should call run_pipeline_async so it doesn't block the request thread.
    """
    # Mark running
    _STATE.set_running(True)
    _STATE.set_error("")

    try:
        logger.info("Pipeline start")
        logger.info("Inputs: pdf=%r, folder=%r, target_date=%r", pdf, folder, target_date)

        # Late import so the just-edited config.py is always the one used by children
        import importlib
        import config  # type: ignore

        # Resolve parameters with config fallbacks
        folder = folder or getattr(config, "FOLDER_NAME", "run_default")
        target_date = target_date or getattr(config, "TARGET_DATE", "01/01")

        logger.info("Resolved params -> folder=%r, target_date=%r", folder, target_date)

        # Prepare destination
        base_dir = Path(getattr(config, "BASE_DIR"))
        folder_path = base_dir / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info("Run folder: %s", folder_path)

        # Copy PDF into run folder
        pdf_src = Path(pdf)
        if not pdf_src.exists():
            raise FileNotFoundError(f"Uploaded PDF does not exist: {pdf_src}")

        pdf_filename = pdf_src.name
        destination_pdf = folder_path / pdf_filename
        shutil.copy2(pdf_src, destination_pdf)
        size_kb = destination_pdf.stat().st_size / 1024.0
        logger.info("Copied PDF to %s (%.1f KB)", destination_pdf, size_kb)

        # Update config.py so that children read the fresh run context
        update_config(folder, target_date, pdf_filename)

        # Force-reload config in THIS process so the log below shows the new values too
        importlib.invalidate_caches()
        config = importlib.reload(config)  # type: ignore
        logger.info("config after update: FOLDER_NAME=%r TARGET_DATE=%r PDF_FILE=%r",
                    getattr(config, "FOLDER_NAME", None),
                    getattr(config, "TARGET_DATE", None),
                    getattr(config, "PDF_FILE", None))

        # Execute the 4 pipeline steps
        run_step("utils.py", "Preparing CSV and merging PDFs")
        run_step("pdf.py", "Extracting data from PDF")
        run_step("CreationReservation.py", "Creating accounts and making reservations")
        run_step("login.py", "Retrying reservations for remaining users")

        logger.info("Pipeline finished successfully.")
    except subprocess.CalledProcessError as e:
        _STATE.set_error(str(e))
        logger.exception("Pipeline step failed.")
        raise
    except Exception as e:
        _STATE.set_error(str(e))
        logger.exception("Pipeline failed with an unexpected error.")
        raise
    finally:
        _STATE.set_running(False)

def run_pipeline_async(*, pdf: str, folder: str | None, target_date: str | None) -> threading.Thread:
    """
    Fire-and-forget runner for Flask UI. Returns the background thread.
    """
    if _STATE.snapshot()["running"]:
        raise RuntimeError("A pipeline is already running.")

    t = threading.Thread(
        target=run_pipeline,
        kwargs=dict(pdf=pdf, folder=folder, target_date=target_date),
        daemon=True,
        name="pipeline-thread",
    )
    t.start()
    return t

# ===== CLI ====================================================================

def main():
    parser = argparse.ArgumentParser(description="Full reservation pipeline runner.")
    parser.add_argument("pdf", help="Path to the PDF file to process.")
    parser.add_argument("--folder", default=None, help="Folder name under BASE_DIR to use.")
    parser.add_argument("--target-date", default=None, help="Target reservation date (DD/MM).")
    # Removed: --hijri-day, --country
    args = parser.parse_args()

    logger.info("CLI args: %s", vars(args))
    try:
        run_pipeline(
            pdf=args.pdf,
            folder=args.folder,
            target_date=args.target_date,
        )
    except Exception:
        # already logged
        raise

if __name__ == "__main__":
    main()
