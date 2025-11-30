"""
Tests for configuration
"""

import os
import pytest
from fritz_monitoring.config import Settings


def test_settings_from_env(monkeypatch):
    """Test loading settings from environment"""
    monkeypatch.setenv("FRITZ_HOST", "192.168.1.1")
    monkeypatch.setenv("FRITZ_PASSWORD", "test_pass")
    
    settings = Settings()  # type: ignore
    
    assert settings.fritz_host == "192.168.1.1"
    assert settings.fritz_password == "test_pass"


def test_settings_defaults():
    """Test default settings values"""
    os.environ.pop("FRITZ_PASSWORD", None)
    
    # Should use defaults except password which is required
    with pytest.raises(Exception):
        Settings()  # type: ignore


def test_fritz_url_generation(monkeypatch):
    """Test Fritz URL generation"""
    monkeypatch.setenv("FRITZ_HOST", "192.168.178.1")
    monkeypatch.setenv("FRITZ_PORT", "49000")
    monkeypatch.setenv("FRITZ_PASSWORD", "test")
    
    settings = Settings()  # type: ignore
    assert settings.fritz_url == "http://192.168.178.1:49000"
