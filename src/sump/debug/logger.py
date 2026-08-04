"""鍒嗙骇鏃ュ織 (Warn/Error/KeyOutput)"""

import logging


logger = logging.getLogger("sump")


def setup_logger(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))