import logging


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure application logs once, without changing Uvicorn or library logs."""
    logger = logging.getLogger("capstone")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Use fixed messages and IDs; never log credentials, payloads, or raw DB errors."""
    return logging.getLogger(f"capstone.{name}")


def debug(name: str, message: str, *args) -> None:
    get_logger(name).debug(message, *args, stacklevel=2)


def info(name: str, message: str, *args) -> None:
    get_logger(name).info(message, *args, stacklevel=2)


def warning(name: str, message: str, *args) -> None:
    get_logger(name).warning(message, *args, stacklevel=2)


def error(name: str, message: str, *args) -> None:
    get_logger(name).error(message, *args, stacklevel=2)


def critical(name: str, message: str, *args) -> None:
    get_logger(name).critical(message, *args, stacklevel=2)


def exception(name: str, message: str, *args) -> None:
    """Log at ERROR with a traceback; use only when exception details are safe."""
    get_logger(name).exception(message, *args, stacklevel=2)
