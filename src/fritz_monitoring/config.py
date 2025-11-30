"""
Configuration management using Pydantic Settings
"""

from pydantic_settings import BaseSettings
from functools import cached_property


class Settings(BaseSettings):
    """Application settings"""

    # Fritz!Box Configuration
    fritz_host: str = "192.168.178.1"
    fritz_port: int = 49000
    fritz_username: str = "dslf"
    fritz_password: str

    # Exporter Configuration
    exporter_port: int = 8000
    exporter_host: str = "0.0.0.0"

    # InfluxDB Configuration
    influxdb_host: str = "localhost"
    influxdb_port: int = 8086
    influxdb_database: str = "fritz_monitoring"
    influxdb_username: str = "admin"
    influxdb_password: str | None = None

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/fritz_monitoring.log"

    # Collection
    collection_interval: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = False

    @cached_property
    def fritz_url(self) -> str:
        """Build Fritz!Box connection URL"""
        return f"http://{self.fritz_host}:{self.fritz_port}"
