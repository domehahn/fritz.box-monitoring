"""Configuration settings for fritz.box-monitoring."""
import os
from functools import cached_property
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Settings for Fritz Monitoring Exporter and Device Manager."""
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_prefix="",
        extra="ignore"
    )

    fritz_host: str = Field(default="192.168.178.1")
    fritz_port: int = Field(default=49000)
    fritz_username: Optional[str] = Field(default=None)
    fritz_password: Optional[str] = Field(default=None)
    fritz_password_file: Optional[str] = Field(default=None)
    fritz_use_tls: bool = Field(default=False)
    fritz_timeout: float = Field(default=5.0)

    exporter_host: str = Field(default="0.0.0.0")
    exporter_port: int = Field(default=8000)
    exporter_collection_interval: float = Field(default=30.0)
    exporter_ready_max_age: float = Field(default=120.0)

    device_manager_admin_password: Optional[str] = Field(default=None)
    device_manager_admin_password_file: Optional[str] = Field(default=None)

    log_level: str = Field(default="INFO")

    @property
    def resolved_password(self) -> Optional[str]:
        """Resolve Fritz password prioritizing FRITZ_PASSWORD_FILE over FRITZ_PASSWORD."""
        if self.fritz_password_file:
            path = self.fritz_password_file.strip()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except Exception as exc:
                    raise RuntimeError(f"Failed to read fritz_password_file '{path}': {exc}") from exc
            else:
                raise RuntimeError(f"fritz_password_file '{path}' does not exist")
        return self.fritz_password

    @property
    def resolved_device_manager_admin_password(self) -> Optional[str]:
        """Resolve Device Manager admin password prioritizing FILE over direct ENV."""
        if self.device_manager_admin_password_file:
            path = self.device_manager_admin_password_file.strip()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except Exception as exc:
                    raise RuntimeError(f"Failed to read device_manager_admin_password_file '{path}': {exc}") from exc
            else:
                raise RuntimeError(f"device_manager_admin_password_file '{path}' does not exist")
        return self.device_manager_admin_password

    @cached_property
    def fritz_base_url(self) -> str:
        protocol = "https" if self.fritz_use_tls else "http"
        return f"{protocol}://{self.fritz_host}:{self.fritz_port}"