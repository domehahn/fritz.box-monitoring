from loguru import logger
import sys

def setup_logging(level: str = "INFO"):
    logger.remove()
    logger.add(sys.stderr, level=level)
