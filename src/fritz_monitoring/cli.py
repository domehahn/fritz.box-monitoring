"""
CLI entry point for Fritz!Box monitoring
"""

import asyncio
import click
from pathlib import Path

from .config import Settings
from .logger import setup_logger
from .collector import FritzBoxCollector
from .exporter import FritzBoxExporter
from .server import MetricsServer

from loguru import logger


@click.group()
def cli() -> None:
    """Fritz!Box Monitoring System CLI"""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0", help="Exporter host")
@click.option("--port", default=8000, help="Exporter port")
@click.option("--log-level", default="INFO", help="Log level")
def run(host: str, port: int, log_level: str) -> None:
    """Run the monitoring exporter"""
    # Load settings
    settings = Settings()  # type: ignore
    
    # Setup logging
    setup_logger(log_level=log_level, log_file=settings.log_file)
    logger.info("Starting Fritz!Box Monitoring System")
    logger.info(f"Fritz!Box: {settings.fritz_host}:{settings.fritz_port}")

    # Create components
    collector = FritzBoxCollector(
        host=settings.fritz_host,
        username=settings.fritz_username,
        password=settings.fritz_password,
        port=settings.fritz_port,
    )
    exporter = FritzBoxExporter()
    server = MetricsServer(exporter, collector)

    # Run server
    asyncio.run(server.start(host or settings.exporter_host, port or settings.exporter_port))
    logger.info(f"Metrics available at http://{host or settings.exporter_host}:{port or settings.exporter_port}/metrics")

    # Keep running
    try:
        asyncio.run(asyncio.sleep(float("inf")))
    except KeyboardInterrupt:
        logger.info("Shutdown requested")


def main() -> None:
    """Entry point"""
    cli()


if __name__ == "__main__":
    main()
