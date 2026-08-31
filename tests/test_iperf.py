"""Unit tests for the opt-in iperf3 probe (parsing + config guards)."""
from fritz_monitoring.iperf.probe import (
    DURATION_CAP,
    INTERVAL_FLOOR,
    IperfConfig,
    IperfExporter,
    IperfResult,
    parse_iperf_json,
)

_OK = {
    "end": {
        "sum_sent": {"bits_per_second": 943000000.0, "retransmits": 12},
        "sum_received": {"bits_per_second": 940500000.0},
    }
}


def test_parse_success():
    r = parse_iperf_json(_OK)
    assert r.success
    assert r.sent_bps == 943000000.0
    assert r.received_bps == 940500000.0
    assert r.retransmits == 12


def test_parse_error_document():
    r = parse_iperf_json({"error": "unable to connect to server: Connection refused"})
    assert not r.success
    assert "Connection refused" in r.error


def test_parse_missing_fields_is_safe():
    r = parse_iperf_json({"end": {}})
    assert r.success and r.sent_bps == 0.0 and r.retransmits == 0.0


def test_config_floors_interval_and_caps_duration(monkeypatch):
    monkeypatch.setenv("IPERF_TARGET", "10.0.0.9")
    monkeypatch.setenv("IPERF_INTERVAL_SECONDS", "5")  # below floor
    monkeypatch.setenv("IPERF_DURATION_SECONDS", "600")  # above cap
    cfg = IperfConfig.from_env()
    assert cfg.interval_seconds == INTERVAL_FLOOR
    assert cfg.duration_seconds == DURATION_CAP
    assert cfg.target == "10.0.0.9"


def test_config_disabled_without_target(monkeypatch):
    monkeypatch.delenv("IPERF_TARGET", raising=False)
    assert IperfConfig.from_env().target is None


def test_exporter_update_render():
    exp = IperfExporter()
    exp.update(IperfResult(success=True, sent_bps=1e8, received_bps=2e8), enabled=True)
    body = exp.render().decode()
    assert "iperf_enabled 1.0" in body
    assert "iperf_last_run_success 1.0" in body
    assert "iperf_sent_bits_per_second 1e+08" in body

    exp.update(IperfResult(success=False), enabled=False)
    body = exp.render().decode()
    assert "iperf_enabled 0.0" in body
    assert "iperf_last_run_success 0.0" in body
