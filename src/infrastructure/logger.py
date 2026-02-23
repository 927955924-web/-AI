import logging
from logging.handlers import RotatingFileHandler

from .paths import app_log_path


_LOGGER = None


def get_logger(name="电商客服"):
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    log_file = app_log_path()
    handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _LOGGER = logger
    return logger

