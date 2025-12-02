"""Config for Fritz!Box exporter."""
from pydantic_settings import BaseSettings
from functools import cached_property

class Settings(BaseSettings):
    fritz_host: str = "192.168.178.1"
    fritz_port: int = 49000
    fritz_username: str = "dslf"
    fritz_password: str

    exporter_host: str = "0.0.0.0"
    exporter_port: int = 8000

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False

    @cached_property
    def fritz_base_url(self) -> str:
        return f"http://{self.fritz_host}:{self.fritz_port}"