"""Unit tests for the smart-home exporters.

Every exporter's I/O is isolated behind one function; these tests exercise the
pure parsing/mapping core and the Prometheus exposition with canned payloads —
no hub, no network.
"""
from types import SimpleNamespace

from home_iot.common import env_bool, env_float, read_secret
from home_iot.blink.exporter import BlinkExporter, to_metric_rows
from home_iot.bosch.exporter import BoschExporter, read_devices
from home_iot.fritzdect.exporter import FritzDectExporter, parse_devices
from home_iot.hue.exporter import (
    HueExporter,
    _lux_from_level,
    parse_resources,
)


# --------------------------------------------------------------------------- #
# common
# --------------------------------------------------------------------------- #
def test_env_helpers(monkeypatch, tmp_path):
    monkeypatch.setenv("X_FLOAT", "3.5")
    assert env_float("X_FLOAT", 1.0) == 3.5
    assert env_float("X_FLOAT", 1.0, floor=10.0) == 10.0
    assert env_float("MISSING", 2.0) == 2.0
    monkeypatch.setenv("X_BOOL", "YES")
    assert env_bool("X_BOOL") is True
    assert env_bool("MISSING", True) is True

    secret = tmp_path / "k.txt"
    secret.write_text("  hunter2\n")
    assert read_secret(str(secret)) == "hunter2"
    assert read_secret("literal-value") == "literal-value"


# --------------------------------------------------------------------------- #
# Hue
# --------------------------------------------------------------------------- #
_HUE_RAW = {
    "device": [
        {
            "id": "dev-1",
            "metadata": {"name": "Kitchen ceiling", "archetype": "ceiling_round"},
            "product_data": {"model_id": "LTA001", "product_name": "Hue ambiance"},
            "services": [{"rtype": "zigbee_connectivity", "rid": "zc-1"}],
        },
        {
            "id": "dev-2",
            "metadata": {"name": "Hallway motion", "archetype": "unknown_archetype"},
            "product_data": {"model_id": "SML001"},
            "services": [{"rtype": "zigbee_connectivity", "rid": "zc-2"}],
        },
    ],
    "zigbee_connectivity": [
        {"owner": {"rid": "dev-1"}, "status": "connected"},
        {"owner": {"rid": "dev-2"}, "status": "connectivity_issue"},
    ],
    "light": [
        {
            "owner": {"rid": "dev-1"},
            "on": {"on": True},
            "dimming": {"brightness": 42.0},
        },
    ],
    "device_power": [
        {
            "owner": {"rid": "dev-2"},
            "power_state": {"battery_level": 78, "battery_state": "normal"},
        },
    ],
    "temperature": [
        {"owner": {"rid": "dev-2"}, "temperature": {"temperature": 21.4}},
    ],
    "light_level": [
        {"owner": {"rid": "dev-2"}, "light": {"light_level": 12000}},
    ],
    "motion": [
        {"owner": {"rid": "dev-2"}, "motion": {"motion": True}},
    ],
    "bridge": [{"bridge_id": "001788fffe1234ab"}],
}


def test_hue_parse_resources_joins_owner_graph():
    snap = parse_resources(_HUE_RAW)
    assert set(snap.devices) == {"dev-1", "dev-2"}
    assert snap.devices["dev-1"].name == "Kitchen ceiling"
    assert snap.connectivity == {"dev-1": 1, "dev-2": 0}
    assert snap.bridge_id == "001788fffe1234ab"


def test_hue_lux_conversion_monotonic():
    assert _lux_from_level(0) == 0.0
    assert _lux_from_level(20000) > _lux_from_level(10000) > 0


def test_hue_exporter_update_renders_expected_series():
    exp = HueExporter()
    exp.update(parse_resources(_HUE_RAW), configured=True, ok=True, seconds=0.2)
    body = exp.render().decode()
    assert "hue_up 1.0" in body
    assert "hue_zigbee_issue_count 1.0" in body
    assert (
        'hue_zigbee_connectivity_status{archetype="ceiling_round",model="LTA001",name="Kitchen ceiling"} 1.0'
        in body
    )
    assert (
        'hue_light_brightness_percent{archetype="ceiling_round",model="LTA001",name="Kitchen ceiling"} 42.0'
        in body
    )
    assert (
        'hue_device_battery_percent{archetype="unknown_archetype",model="SML001",name="Hallway motion"} 78.0'
        in body
    )
    assert (
        'hue_sensor_motion{archetype="unknown_archetype",model="SML001",name="Hallway motion"} 1.0'
        in body
    )


def test_hue_exporter_unconfigured_is_healthy_but_zero():
    exp = HueExporter()
    exp.update(None, configured=False, ok=False, seconds=0.0)
    body = exp.render().decode()
    assert "hue_configured 0.0" in body
    assert "hue_up 0.0" in body


# --------------------------------------------------------------------------- #
# FRITZ!DECT
# --------------------------------------------------------------------------- #
_DECT_RAW = [
    {
        "NewAIN": "11657 0272633",
        "NewDeviceName": "Waschmaschine",
        "NewProductName": "FRITZ!DECT 200",
        "NewPresent": "1",
        "NewMultimeterPower": "1234",  # 0.01 W -> 12.34 W
        "NewMultimeterEnergy": "875000",  # Wh
        "NewTemperatureCelsius": "212",  # 0.1 C -> 21.2 C
        "NewSwitchState": "1",
    },
    {
        "NewAIN": "09995 0123456",
        "NewDeviceName": "Heizung Bad",
        "NewProductName": "FRITZ!DECT 301",
        "NewPresent": "1",
        "NewHkrSetTemperature": "42",  # /2 -> 21.0 C
        "NewHkrComfortTemperature": "44",  # /2 -> 22.0 C
        "NewHkrSetVentilStatus": "1",
    },
    {
        "NewAIN": "dead",
        "NewDeviceName": "Alte Steckdose",
        "NewProductName": "FRITZ!DECT 200",
        "NewPresent": "0",
        "NewMultimeterPower": "inval",
    },
]


def test_fritzdect_parse_units():
    devs = {d.ain: d for d in parse_devices(_DECT_RAW)}
    plug = devs["11657 0272633"]
    assert plug.power_w == 12.34
    assert plug.energy_wh == 875000
    assert plug.temperature_c == 21.2
    assert plug.switch_on == 1
    hkr = devs["09995 0123456"]
    assert hkr.hkr_set_c == 21.0
    assert hkr.hkr_comfort_c == 22.0
    assert hkr.hkr_valve_open == 1
    dead = devs["dead"]
    assert dead.present == 0
    assert dead.power_w is None


def test_fritzdect_exporter_render():
    exp = FritzDectExporter()
    exp.update(parse_devices(_DECT_RAW), configured=True, ok=True)
    body = exp.render().decode()
    assert "fritzdect_up 1.0" in body
    assert (
        'fritzdect_power_watts{ain="11657 0272633",name="Waschmaschine",product="FRITZ!DECT 200"} 12.34'
        in body
    )
    assert "fritzdect_device_count 3.0" in body


# --------------------------------------------------------------------------- #
# Bosch
# --------------------------------------------------------------------------- #
def _bosch_session():
    svc_temp = SimpleNamespace(id="TemperatureLevel", state={"temperature": 19.5})
    svc_hum = SimpleNamespace(id="HumidityLevel", state={"humidity": 55})
    dev_climate = SimpleNamespace(
        id="hz-1",
        name="Wohnzimmer Thermostat",
        device_model="TRV",
        room_id="Wohnzimmer",
        status="AVAILABLE",
        batterylevel=SimpleNamespace(name="OK"),
        device_services=[svc_temp],
    )
    dev_sensor = SimpleNamespace(
        id="sc-1",
        name="Fenster Küche",
        device_model="SWD",
        room_id="Küche",
        status="DISCONNECTED",
        batterylevel=SimpleNamespace(name="LOW_BATTERY"),
        device_services=[svc_hum],
    )
    return SimpleNamespace(
        information=SimpleNamespace(
            version="10.19.1234", updateState="NO_UPDATE_AVAILABLE"
        ),
        devices=[dev_climate, dev_sensor],
    )


def test_bosch_read_devices_and_render():
    snap = read_devices(_bosch_session())
    assert snap.shc_version == "10.19.1234"
    assert snap.shc_update_available == 0
    by = {d.name: d for d in snap.devices}
    assert by["Wohnzimmer Thermostat"].available == 1
    assert by["Wohnzimmer Thermostat"].temperature_c == 19.5
    assert by["Wohnzimmer Thermostat"].battery_ok == 1
    assert by["Fenster Küche"].available == 0
    assert by["Fenster Küche"].battery_ok == 0
    assert by["Fenster Küche"].humidity_pct == 55.0

    exp = BoschExporter()
    exp.update(snap, configured=True, ok=True)
    body = exp.render().decode()
    assert "bosch_shc_up 1.0" in body
    assert "bosch_shc_battery_low_count 1.0" in body
    assert (
        'bosch_device_available{device="Fenster Küche",model="SWD",room="Küche"} 0.0'
        in body
    )


# --------------------------------------------------------------------------- #
# Blink
# --------------------------------------------------------------------------- #
_BLINK_CAMERAS = {
    "Einfahrt": {
        "name": "Einfahrt",
        "network_id": "12345",
        "battery": "ok",
        "battery_voltage": 158,
        "temperature": 71,  # F -> 21.7 C
        "wifi_strength": 3,
        "motion_enabled": True,
        "motion_detected": False,
    },
    "Garten": {
        "name": "Garten",
        "network_id": "12345",
        "battery": "low",
        "temperature_c": 18.0,
        "motion_enabled": False,
    },
}
_BLINK_SYNC = {"Haus": {"status": "online"}, "Schuppen": {"status": "offline"}}


def test_blink_to_metric_rows():
    snap = to_metric_rows(_BLINK_CAMERAS, _BLINK_SYNC)
    by = {c.name: c for c in snap.cameras}
    assert by["Einfahrt"].battery_ok == 1
    assert by["Einfahrt"].temperature_c == 21.7
    assert by["Einfahrt"].motion_enabled == 1
    assert by["Garten"].battery_ok == 0
    assert by["Garten"].temperature_c == 18.0
    assert snap.sync_modules == {"Haus": 1, "Schuppen": 0}


def test_blink_exporter_render():
    exp = BlinkExporter()
    exp.update(to_metric_rows(_BLINK_CAMERAS, _BLINK_SYNC), configured=True, ok=True)
    body = exp.render().decode()
    assert "blink_up 1.0" in body
    assert "blink_camera_count 2.0" in body
    assert 'blink_sync_module_online{name="Schuppen"} 0.0' in body
