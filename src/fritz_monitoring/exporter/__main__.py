"""Entry point for running the exporter as a module."""
import asyncio
from .server import MetricsServer
from ..config import Settings


def main():
    settings = Settings()
    server = MetricsServer(settings)
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
