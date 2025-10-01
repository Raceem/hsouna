import logging
import os
import shutil
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler that tolerates Windows file-in-use errors during
    rollover by falling back to copy+truncate.

    This avoids PermissionError: [WinError 32] when another handler/process
    temporarily holds the log file open at the moment of rotation.
    """

    def rotate(self, source, dest):  # type: ignore[override]
        try:
            # Prefer atomic replace when available
            os.replace(source, dest)
        except PermissionError:
            try:
                shutil.copy2(source, dest)
                # Truncate original file to continue logging
                with open(source, "w", encoding=self.encoding or "utf-8"):
                    pass
            except Exception:
                # Give up silently; logging should not crash the app
                return


def get_shared_logger(name: str = "reservation", log_file: str | None = None) -> logging.Logger:
    """
    Create or return a shared application logger.

    - Adds a single SafeRotatingFileHandler to avoid Windows rename races.
    - Adds a single console handler.
    - Does not clear existing handlers; it only adds missing ones.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if log_file is None:
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "automation.log")

    # File handler (add once)
    have_file = any(isinstance(h, RotatingFileHandler) for h in logger.handlers)
    if not have_file:
        fh = SafeRotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

    # Console handler (add once)
    have_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in logger.handlers)
    if not have_console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(ch)

    return logger

