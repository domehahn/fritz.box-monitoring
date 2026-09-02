"""Unit tests for the smart-home exporters.

Every exporter's I/O is isolated behind one function; these tests exercise the
pure parsing/mapping core and the Prometheus exposition with canned payloads —
no hub, no network.
"""
from types import SimpleNamespace

import pytest

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


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #
def test_weather_parse_current():
    from home_iot.weather.exporter import WeatherExporter, parse_current

    w = {
        "temperature": 4.2,
        "relative_humidity": 88,
        "wind_speed_10": 11.0,
        "wind_gust_speed_10": 34.0,
        "precipitation_10": 0.3,
        "cloud_cover": 75,
        "pressure_msl": 1013.2,
        "solar_10": 0.02,
        "visibility": 21200,
        "condition": "rain",
        "icon": "rain",
    }
    r = parse_current(w)
    assert r.temperature_c == 4.2
    assert r.humidity_pct == 88.0
    assert r.wind_gust_kmh == 34.0
    assert r.condition == "rain"

    exp = WeatherExporter()
    exp.update(r, configured=True, ok=True)
    body = exp.render().decode()
    assert "weather_up 1.0" in body
    assert "weather_temperature_celsius 4.2" in body
    assert 'weather_condition_info{condition="rain",icon="rain"} 1.0' in body


def test_weather_config_params():
    from home_iot.weather.exporter import WeatherConfig

    assert not WeatherConfig("", "", "").configured
    assert WeatherConfig("52.5", "13.4", "").params == {"lat": "52.5", "lon": "13.4"}
    assert WeatherConfig("", "", "01766").params == {"dwd_station_id": "01766"}


# --------------------------------------------------------------------------- #
# Speedtest
# --------------------------------------------------------------------------- #
def test_speedtest_summarise():
    from home_iot.speedtest.exporter import summarise

    lo, jit = summarise([0.030, 0.032, 0.031, 0.0])
    assert lo == 0.030
    assert jit > 0
    assert summarise([]) == (0.0, 0.0)


def test_speedtest_exporter_render():
    from home_iot.speedtest.exporter import SpeedtestExporter, SpeedtestResult

    exp = SpeedtestExporter()
    exp.update(
        SpeedtestResult(
            success=True,
            download_bps=9.4e8,
            upload_bps=4.1e7,
            latency_s=0.012,
            jitter_s=0.003,
            bytes_down=104857600,
            bytes_up=52428800,
        )
    )
    body = exp.render().decode()
    assert "speedtest_up 1.0" in body
    assert "speedtest_download_bits_per_second 9.4e+08" in body


# --------------------------------------------------------------------------- #
# Bosch (extended P2 fields)
# --------------------------------------------------------------------------- #
def test_bosch_reads_power_contact_air_intrusion():
    svc_pm = SimpleNamespace(
        id="PowerMeter", state={"powerConsumption": 17.0, "energyConsumption": 390390.0}
    )
    svc_sw = SimpleNamespace(id="PowerSwitch", state={"switchState": "ON"})
    svc_sc = SimpleNamespace(id="ShutterContact", state={"value": "OPEN"})
    svc_aq = SimpleNamespace(
        id="AirQualityLevel",
        state={
            "combinedRating": "MEDIUM",
            "purity": 670,
            "temperature": 23.4,
            "humidity": 58.0,
        },
    )
    svc_alarm = SimpleNamespace(id="Alarm", state={"value": "IDLE_OFF"})
    plug = SimpleNamespace(
        id="p1",
        name="Technikraum",
        device_model="PLUG_COMPACT",
        room_id="r_tech",
        status="AVAILABLE",
        batterylevel=None,
        device_services=[svc_pm, svc_sw],
    )
    window = SimpleNamespace(
        id="w1",
        name="Küche Fenster",
        device_model="SWD",
        room_id="r_kitchen",
        status="AVAILABLE",
        batterylevel=SimpleNamespace(name="OK"),
        device_services=[svc_sc],
    )
    twin = SimpleNamespace(
        id="t1",
        name="Wohnzimmer Luft",
        device_model="TWINGUARD",
        room_id="r_living",
        status="AVAILABLE",
        batterylevel=None,
        device_services=[svc_aq, svc_alarm],
    )
    session = SimpleNamespace(
        information=SimpleNamespace(version="10.35", updateState="NO_UPDATE_AVAILABLE"),
        rooms=[
            SimpleNamespace(id="r_tech", name="Technikraum"),
            SimpleNamespace(id="r_kitchen", name="Küche"),
            SimpleNamespace(id="r_living", name="Wohnzimmer"),
        ],
        devices=[plug, window, twin],
        intrusion_system=SimpleNamespace(
            arming_state="SYSTEM_DISARMED",
            alarm_state="ALARM_OFF",
            system_availability=True,
        ),
    )
    snap = read_devices(session)
    by = {d.name: d for d in snap.devices}
    assert by["Technikraum"].power_w == 17.0
    assert by["Technikraum"].energy_wh == 390390.0
    assert by["Technikraum"].switch_on == 1
    assert by["Technikraum"].room == "Technikraum"
    assert by["Küche Fenster"].contact_open == 1
    assert by["Wohnzimmer Luft"].air_purity_ppm == 670.0
    assert by["Wohnzimmer Luft"].air_rating == 1
    assert by["Wohnzimmer Luft"].smoke_alarm == 0
    assert snap.intrusion_armed == 0
    assert snap.intrusion_alarm == 0

    exp = BoschExporter()
    exp.update(snap, configured=True, ok=True)
    body = exp.render().decode()
    assert "bosch_shc_total_power_watts 17.0" in body
    assert "bosch_intrusion_armed 0.0" in body
    assert (
        'bosch_device_contact_open{device="Küche Fenster",model="SWD",room="Küche"} 1.0'
        in body
    )


# --------------------------------------------------------------------------- #
# FRITZ!Box device log
# --------------------------------------------------------------------------- #
def test_devicelog_parse_and_classify():
    from fritz_monitoring.devicelog import DeviceLogTailer, parse_log

    raw = (
        "31.08.26 14:03:12 Internetverbindung wurde getrennt.\n"
        "31.08.26 14:03:40 Anmeldung des Internetzugangs war erfolgreich.\n"
        "31.08.26 09:15:00 WLAN-Geraet angemeldet: Handy.\n"
        "garbage line without timestamp\n"
    )
    evs = parse_log(raw)
    assert len(evs) == 3
    assert evs[0]["subsystem"] == "wan"
    assert evs[0]["severity"] == "warning"
    assert evs[2]["subsystem"] == "wifi"

    tailer = DeviceLogTailer(min_interval_s=0)

    class _FC:
        def call_action(self, *_):
            return {"NewDeviceLog": raw}

    client = SimpleNamespace(fc=_FC())
    assert tailer.poll(client) == []  # first poll only primes
    assert tailer.poll(client) == []  # nothing new
    client.fc = _FC.__new__(_FC)
    client.fc.call_action = lambda *_: {
        "NewDeviceLog": "31.08.26 15:00:00 Neustart durchgefuehrt.\n" + raw
    }
    fresh = tailer.poll(client)
    assert len(fresh) == 1 and fresh[0]["subsystem"] == "system"


# --------------------------------------------------------------------------- #
# dockerstats
# --------------------------------------------------------------------------- #
def test_dockerstats_cpu_and_parse():
    from home_iot.dockerstats.exporter import (
        DockerStatsExporter,
        cpu_percent,
        parse_stats,
    )

    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2000},
            "system_cpu_usage": 20000,
            "online_cpus": 4,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 10000},
        "memory_stats": {
            "usage": 200_000_000,
            "limit": 512_000_000,
            "stats": {"inactive_file": 50_000_000},
        },
        "networks": {"eth0": {"rx_bytes": 1234, "tx_bytes": 567}},
    }
    assert cpu_percent(stats) == 40.0  # (1000/10000)*4*100
    container = {
        "Names": ["/fritz-exporter"],
        "State": "running",
        "Status": "Up 3 hours (healthy)",
    }
    cs = parse_stats(container, stats, restart_count=2)
    assert cs.name == "fritz-exporter"
    assert cs.state == "running"
    assert cs.restart_count == 2
    assert cs.mem_bytes == 150_000_000
    assert cs.net_rx_bytes == 1234
    assert cs.health == 1

    exp = DockerStatsExporter()
    exp.update([cs], ok=True)
    body = exp.render().decode()
    assert "dockerstats_up 1.0" in body
    assert 'docker_container_cpu_percent{name="fritz-exporter"} 40.0' in body


def test_dockerstats_cpu_zero_on_bad_input():
    from home_iot.dockerstats.exporter import cpu_percent

    assert cpu_percent({}) == 0.0
    assert cpu_percent({"cpu_stats": {}, "precpu_stats": {}}) == 0.0


# --------------------------------------------------------------------------- #
# alertbridge
# --------------------------------------------------------------------------- #
def test_alertbridge_format_alert():
    from home_iot.alertbridge.app import format_alert

    firing = {
        "status": "firing",
        "labels": {
            "alertname": "BoschSmokeAlarm",
            "severity": "critical",
            "device": "Flur",
            "room": "Flur",
        },
        "annotations": {
            "summary": "SMOKE ALARM — Flur",
            "description": "detector in alarm",
        },
    }
    title, body, prio, tags = format_alert(firing)
    assert "CRITICAL" in title and "SMOKE ALARM" in title
    assert prio == "5"
    assert "detector in alarm" in body
    assert "device=Flur" in body

    resolved = {
        "status": "resolved",
        "labels": {"alertname": "HostDown", "severity": "critical"},
        "annotations": {"summary": "node-exporter is down"},
    }
    _, _, prio_r, tags_r = format_alert(resolved)
    assert prio_r == "3" and tags_r == "white_check_mark"

    info = {
        "status": "firing",
        "labels": {"alertname": "RoomHighHumidity", "severity": "info"},
        "annotations": {},
    }
    _, _, prio_i, _ = format_alert(info)
    assert prio_i == "2"


def test_alertbridge_ascii_header():
    from home_iot.alertbridge.app import _ascii

    assert _ascii("🚨 CRITICAL: x") == "CRITICAL: x"
    assert _ascii("🚨🚨🚨") == "alert"


@pytest.mark.asyncio
async def test_alertbridge_watchdog_updates_state(monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    from home_iot.alertbridge import app

    monkeypatch.setattr(app, "_last_watchdog", 0.0, raising=False)
    app._watchdog_seen.set(0.0)
    # no DEADMAN_URL -> no outbound request
    resp = await app.handle_watchdog(make_mocked_request("POST", "/watchdog"))
    assert resp.status == 200
    assert app._last_watchdog > 0.0
    body = app.generate_latest().decode()
    assert "alertbridge_watchdog_last_seen_timestamp_seconds" in body


@pytest.mark.asyncio
async def test_alertbridge_watchdog_pings_deadman_url(monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    from home_iot.alertbridge import app

    hits = []
    monkeypatch.setenv("DEADMAN_URL", "https://hc.example/ping/abc")
    monkeypatch.setattr(app.requests, "get", lambda url, timeout=0: hits.append(url))
    await app.handle_watchdog(make_mocked_request("GET", "/watchdog"))
    assert hits == ["https://hc.example/ping/abc"]


# --------------------------------------------------------------------------- #
# energy
# --------------------------------------------------------------------------- #
def test_energy_awattar_price_stats():
    from home_iot.energy.exporter import awattar_slots, price_stats

    # 24 hourly slots starting at midnight UTC; prices 100..330 Eur/MWh
    base = 1_700_000_000
    base -= base % 86400  # midnight
    data = {
        "data": [
            {
                "start_timestamp": (base + i * 3600) * 1000,
                "end_timestamp": (base + (i + 1) * 3600) * 1000,
                "marketprice": 100 + i * 10,
            }
            for i in range(24)
        ]
    }
    slots = awattar_slots(data)
    assert len(slots) == 24 and slots[0]["eur_kwh"] == 0.1

    now = base + 3 * 3600 + 60  # inside slot 3 (130 Eur/MWh = 0.13 Eur/kWh)
    snap = price_stats(slots, now, vat=1.0, surcharge_ct_kwh=0.0)
    assert snap.spot_eur_kwh == 0.13
    assert snap.consumer_eur_kwh == 0.13
    assert snap.min_today == 0.1 and snap.max_today == 0.33
    assert 0.12 < snap.rank_today < 0.14  # (0.13-0.1)/(0.33-0.1)
    assert snap.level == int(snap.rank_today * 5)
    # VAT + surcharge applied
    snap2 = price_stats(slots, now, vat=1.19, surcharge_ct_kwh=15.0)
    assert snap2.consumer_eur_kwh == round(0.13 * 1.19 + 0.15, 5)


def test_energy_parse_shelly_gen2_and_gen1():
    from home_iot.energy.exporter import parse_shelly

    g2 = {
        "em:0": {
            "total_act_power": 812.4,
            "a_act_power": 300.0,
            "b_act_power": 500.0,
            "c_act_power": 12.4,
        },
        "emdata:0": {"total_act": 1234567.0},
    }
    m = parse_shelly(g2)
    assert m.power_w == 812.4
    assert m.phase_w == {"A": 300.0, "B": 500.0, "C": 12.4}
    assert m.import_wh == 1234567.0

    g1 = {
        "emeters": [{"power": 100.0, "total": 5000.0}, {"power": 50.0, "total": 2000.0}]
    }
    m1 = parse_shelly(g1)
    assert m1.power_w == 150.0
    assert m1.import_wh == 7000.0


def test_energy_parse_tibber():
    from home_iot.energy.exporter import parse_tibber

    gql = {
        "data": {
            "viewer": {
                "homes": [
                    {
                        "currentSubscription": {
                            "priceInfo": {
                                "current": {
                                    "total": 0.2841,
                                    "energy": 0.09,
                                    "tax": 0.19,
                                    "level": "EXPENSIVE",
                                    "startsAt": "x",
                                },
                                "today": [
                                    {"total": 0.20, "startsAt": "a"},
                                    {"total": 0.30, "startsAt": "b"},
                                    {"total": 0.2841, "startsAt": "c"},
                                ],
                                "tomorrow": [{"total": 0.18, "startsAt": "d"}],
                            }
                        },
                        "consumption": {
                            "nodes": [{"consumption": 1.4, "cost": 0.39, "from": "z"}]
                        },
                    }
                ]
            }
        }
    }
    price, meter = parse_tibber(gql, now=1_700_000_000)
    assert price.consumer_eur_kwh == 0.2841
    assert price.level == 3
    assert price.min_today == 0.2 and price.max_today == 0.3
    assert price.min_next12h == 0.18
    assert meter.last_hour_kwh == 1.4 and meter.last_hour_cost_eur == 0.39


def test_energy_exporter_render():
    from home_iot.energy.exporter import (
        EnergyExporter,
        MeterSnapshot,
        PriceSnapshot,
    )

    exp = EnergyExporter()
    exp.update(
        PriceSnapshot(
            source="awattar",
            consumer_eur_kwh=0.28,
            spot_eur_kwh=0.11,
            level=3,
            rank_today=0.72,
            min_today=0.19,
            max_today=0.34,
        ),
        MeterSnapshot(
            source="shelly", power_w=640.0, phase_w={"A": 640.0}, import_wh=1000.0
        ),
        ok=True,
    )
    body = exp.render().decode()
    assert "energy_up 1.0" in body
    assert 'energy_price_eur_per_kwh{source="awattar"} 0.28' in body
    assert 'energy_power_watts{source="shelly"} 640.0' in body
    assert 'energy_phase_power_watts{phase="A",source="shelly"} 640.0' in body


# --------------------------------------------------------------------------- #
# lantap (FRITZ!Box packet-capture per-device accounting)
# --------------------------------------------------------------------------- #
def _eth_ipv4(src: str, dst: str, vlan: bool = False) -> bytes:
    import ipaddress

    mac = b"\x00\x11\x22\x33\x44\x55" + b"\x66\x77\x88\x99\xaa\xbb"
    if vlan:
        l2 = mac + b"\x81\x00" + b"\x00\x01" + b"\x08\x00"
    else:
        l2 = mac + b"\x08\x00"
    ip = (
        b"\x45\x00\x00\x28"
        + b"\x00\x00\x40\x00\x40\x06\x00\x00"
        + ipaddress.IPv4Address(src).packed
        + ipaddress.IPv4Address(dst).packed
    )
    return l2 + ip + b"\x00" * 8


def test_lantap_frame_endpoints_and_classify():
    import ipaddress
    from home_iot.lantap.pcap import classify, frame_endpoints

    nets = [ipaddress.ip_network("192.168.178.0/24")]

    up = _eth_ipv4("192.168.178.42", "1.2.3.4")
    assert frame_endpoints(up) == ("192.168.178.42", "1.2.3.4")
    assert classify(up, 1500, nets) == [("192.168.178.42", "tx", 1500)]

    down = _eth_ipv4("1.2.3.4", "192.168.178.42")
    assert classify(down, 800, nets) == [("192.168.178.42", "rx", 800)]

    lan2lan = _eth_ipv4("192.168.178.10", "192.168.178.20")
    got = classify(lan2lan, 100, nets)
    assert ("192.168.178.10", "tx", 100) in got and ("192.168.178.20", "rx", 100) in got

    vlan = _eth_ipv4("192.168.178.42", "8.8.8.8", vlan=True)
    assert frame_endpoints(vlan) == ("192.168.178.42", "8.8.8.8")

    assert frame_endpoints(b"\x00" * 14) == ("", "")  # non-IP ethertype 0


def test_lantap_pcap_stream_reassembles_records():
    import struct
    from home_iot.lantap.pcap import PcapStream

    f1 = _eth_ipv4("192.168.178.7", "9.9.9.9")
    f2 = _eth_ipv4("9.9.9.9", "192.168.178.7")
    gh_classic = struct.pack(">IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1)
    gh_mod = struct.pack(">IHHiIII", 0xA1B2CD34, 2, 4, 0, 0, 262144, 1)

    def classic(f, orig):
        return struct.pack(">IIII", 1, 0, len(f), orig) + f

    def modified(f, orig):  # +8: ifindex, protocol, pkt_type, pad
        return struct.pack(">IIIIIHBB", 1, 0, len(f), orig, 2, 1, 0, 0) + f

    for gh, mk in ((gh_classic, classic), (gh_mod, modified)):
        blob = gh + mk(f1, 1400) + mk(f2, 600)
        st = PcapStream()
        out = []
        for i in range(0, len(blob), 7):  # awkward slices exercise buffering
            out.extend(st.feed(blob[i : i + 7]))
        assert [o[0] for o in out] == [1400, 600]
        assert out[0][1] == f1


def test_lantap_exporter_counters():
    from home_iot.lantap.exporter import LanTapExporter

    exp = LanTapExporter()
    exp.add("192.168.178.42", "tx", 1500)
    exp.add("192.168.178.42", "rx", 4000)
    exp.add("192.168.178.42", "rx", 4000)
    exp.set_names({"192.168.178.42": ("Gaming-PC", "aa:bb:cc:dd:ee:ff")})
    body = exp.render().decode()
    assert 'lantap_host_sent_bytes_total{ip="192.168.178.42"} 1500.0' in body
    assert 'lantap_host_received_bytes_total{ip="192.168.178.42"} 8000.0' in body
    assert 'lantap_host_received_packets_total{ip="192.168.178.42"} 2.0' in body
    assert (
        'lantap_host_info{ip="192.168.178.42",mac="aa:bb:cc:dd:ee:ff",name="Gaming-PC"} 1.0'
        in body
    )


def test_lantap_login_response_pbkdf2():
    from home_iot.lantap.login import _response

    # deterministic PBKDF2 vector
    r = _response("2$3$00$3$00", "secret")
    assert r.startswith("00$") and len(r.split("$")[1]) == 64


def test_lantap_config_subnets():
    from home_iot.lantap.exporter import LanTapConfig

    cfg = LanTapConfig(
        host="h", username="u", password="p", subnets="192.168.178.0/24, 10.0.0.0/8"
    )
    nets = cfg.nets
    assert len(nets) == 2
    assert cfg.configured
    assert cfg.reconnect_minutes == 30.0


def test_lantap_l4_and_category():
    import struct
    from home_iot.lantap.pcap import category, frame_l4

    def eth_ipv4_l4(proto, sport, dport):
        mac = b"\x00" * 12
        l2 = mac + b"\x08\x00"
        ip = (
            bytes([0x45, 0, 0, 40, 0, 0, 0x40, 0, 0x40, proto, 0, 0])
            + b"\xc0\xa8\xb2\x0a"
            + b"\x08\x08\x08\x08"
        )
        l4 = struct.pack(">HH", sport, dport) + b"\x00" * 4
        return l2 + ip + l4

    assert frame_l4(eth_ipv4_l4(6, 51514, 443)) == (6, 51514, 443)
    assert category(6, 51514, 443) == "web"
    assert category(17, 51514, 443) == "quic"
    assert category(17, 40000, 27020) == "gaming"
    assert category(6, 33333, 53) == "dns"
    assert category(6, 40000, 587) == "mail"
    assert category(17, 44444, 55555) == "p2p/rtc"
    assert category(6, 40000, 40001) == "other"


def test_lantap_classify_flows():
    import ipaddress
    from home_iot.lantap.pcap import classify_flows

    nets = [ipaddress.ip_network("192.168.178.0/24")]
    # local .10 -> 8.8.8.8:53 udp
    mac = b"\x00" * 12
    frame = (
        mac
        + b"\x08\x00"
        + bytes([0x45, 0, 0, 40, 0, 0, 0x40, 0, 0x40, 17, 0, 0])
        + ipaddress.IPv4Address("192.168.178.10").packed
        + ipaddress.IPv4Address("8.8.8.8").packed
        + b"\xdd\xdd\x00\x35"
        + b"\x00" * 4
    )
    out = classify_flows(frame, 120, nets)
    assert out == [("192.168.178.10", "tx", "dns", 120)]


# --------------------------------------------------------------------------- #
# digest (weekly report)
# --------------------------------------------------------------------------- #
def test_digest_seconds_until():
    import datetime as dt
    from home_iot.digest.app import seconds_until

    # Wed 12:00 -> next Monday 09:00 is in 4d 21h
    now = dt.datetime(2026, 9, 2, 12, 0, 0)  # a Wednesday
    s = seconds_until(0, 9, now)
    assert abs(s - ((4 * 24 + 21) * 3600)) < 2
    # same day but earlier hour -> today
    mon = dt.datetime(2026, 8, 31, 7, 0, 0)  # a Monday
    assert abs(seconds_until(0, 9, mon) - 2 * 3600) < 2
    # same day, past the hour -> +7d
    mon_late = dt.datetime(2026, 8, 31, 10, 0, 0)
    assert abs(seconds_until(0, 9, mon_late) - (7 * 24 - 1) * 3600) < 2


def test_digest_build_report():
    from home_iot.digest.report import build_report

    scalars = {
        "avg_over_time(home:network_health:score[7d])": 0.985,
        "min_over_time(home:network_health:score[7d])": 0.7,
        "avg_over_time(home:health:internet_reachability[7d])": 0.999,
        "max(max_over_time(fritz:probe_loss_ratio:5m[7d]))": 0.05,
        "avg_over_time(home:health:dns[7d])": 1.0,
        "avg_over_time(energy_price_eur_per_kwh[7d])": 0.24,
        "increase(energy_import_watt_hours_total[7d]) / 1000": None,
        'count(count by (alertname) (max_over_time(ALERTS{alertstate="firing"}[7d])))': 2.0,
        "time() - backup_last_success_timestamp_seconds": 7200.0,
        "backup_repository_bytes": 4.6e7,
    }
    vectors = {
        "topk(3, sum by (ip) (increase(lantap_host_received_bytes_total[7d])))": [
            ({"ip": "192.168.178.198"}, 8.2e9),
            ({"ip": "192.168.178.10"}, 3.1e9),
        ],
        "lantap_host_info": [({"ip": "192.168.178.198", "name": "Gaming-PC"}, 1.0)],
        'topk(5, count by (alertname) (max_over_time(ALERTS{alertstate="firing"}[7d])))': [
            ({"alertname": "BlinkSyncModuleOffline"}, 1.0)
        ],
    }
    title, body = build_report(
        lambda e: scalars.get(e), lambda e: vectors.get(e, []), "7d"
    )
    assert "Weekly network digest" in title
    assert "of the week" in body
    assert "avg 98.50%" in body
    assert "Gaming-PC — 8.2 GB" in body
    assert "Worst packet loss" in body  # 5% > 2% threshold
    assert "Alerts fired** — 2 distinct" in body
    assert "BlinkSyncModuleOffline" in body
    assert "last 2h ago" in body
    assert "repo 46 MB" in body


def test_digest_build_report_monthly_wording():
    from home_iot.digest.report import build_report

    scalars = {
        "avg_over_time(home:network_health:score[30d])": 0.97,
        "min_over_time(home:network_health:score[30d])": 0.6,
        "avg_over_time(home:health:internet_reachability[30d])": 0.998,
        "avg_over_time(isp:attainment:down_ratio[30d])": 0.88,
        "min_over_time(isp:attainment:down_ratio[30d])": 0.41,
        "count_over_time((isp:attainment:down_ratio < 0.8)[30d:1h])": 6.0,
        "isp:reference:down_mbps": 1000.0,
    }
    title, body = build_report(
        lambda e: scalars.get(e), lambda e: [], "30d", "Monthly"
    )
    assert "Monthly network digest" in title
    assert "of the month" in body
    assert "ISP SLA (evidence)" in body
    assert "1000 Mbit/s" in body
    assert "6 test(s) below 80%" in body


def test_digest_seconds_until_monthly():
    import datetime as dt
    from home_iot.digest.app import seconds_until_monthly

    # Sep 2 12:00 -> Oct 1 09:00 == 28 days 21 hours
    now = dt.datetime(2026, 9, 2, 12, 0, 0)
    s = seconds_until_monthly(1, 9, now)
    assert abs(s - (28 * 24 * 3600 + 21 * 3600)) < 2
    # earlier same day -> today
    now2 = dt.datetime(2026, 9, 1, 7, 0, 0)
    assert abs(seconds_until_monthly(1, 9, now2) - 2 * 3600) < 2
    # December wraps to January
    dec = dt.datetime(2026, 12, 15, 0, 0, 0)
    assert seconds_until_monthly(1, 9, dec) > 0


def test_dockerstats_connection_selects_tcp_or_unix():
    import http.client
    from home_iot.dockerstats.exporter import _connection

    c = _connection("tcp://docker-socket-proxy:2375", 5)
    assert isinstance(c, http.client.HTTPConnection) and c.host == "docker-socket-proxy"
    assert c.port == 2375
    u = _connection("/var/run/docker.sock", 5)
    assert u.__class__.__name__ == "_UnixHTTPConnection"


def test_netwatch_allowlist_and_decide():
    from home_iot.netwatch.exporter import decide, load_allowlist, _allowed

    allow = load_allowlist(
        "# my devices\nAA:BB:CC:DD:EE:FF\n  gaming-pc  # kid\n\n"
    )
    assert allow == ["aa:bb:cc:dd:ee:ff", "gaming-pc"]
    assert _allowed("AA:BB:CC:DD:EE:FF", "whatever", allow)
    assert _allowed("11:22:33:44:55:66", "Kids Gaming-PC", allow)
    assert not _allowed("11:22:33:44:55:66", "printer", allow)

    samples = [
        {"mac": "de:ad:be:ef:00:01", "name": "Known-Phone", "ip": "192.168.178.10",
         "interface": "802.11"},
        {"mac": "de:ad:be:ef:00:02", "name": "New-Thing", "ip": "192.168.178.99"},
    ]
    flags = [1.0, 1.0]
    state = {"DE:AD:BE:EF:00:01": 1_000.0}  # phone seen long ago
    devs, new_state = decide(samples, flags, state, [], now=2_000_000.0)
    by = {d.mac: d for d in devs}
    assert by["DE:AD:BE:EF:00:01"].first_seen == 1_000.0        # preserved
    assert by["DE:AD:BE:EF:00:02"].first_seen == 2_000_000.0    # stamped now
    assert by["DE:AD:BE:EF:00:01"].connection == "wifi"
    assert new_state["DE:AD:BE:EF:00:02"] == 2_000_000.0        # persisted

    # fresh install (empty state) + seed_ts -> everything stamped in the past
    fresh, _ = decide(samples, flags, {}, [], now=2_000_000.0, seed_ts=42.0)
    assert all(d.first_seen == 42.0 for d in fresh)
    # but once state exists, seed_ts is ignored for the genuinely-new MAC
    mixed, _ = decide(samples, flags, {"DE:AD:BE:EF:00:01": 1_000.0}, [],
                      now=2_000_000.0, seed_ts=42.0)
    assert {d.mac: d.first_seen for d in mixed}["DE:AD:BE:EF:00:02"] == 2_000_000.0


def test_netwatch_exporter_flags_new_only():
    from home_iot.netwatch.exporter import NetwatchExporter, decide

    now = 1_000_000.0
    samples = [
        {"mac": "aa:aa:aa:aa:aa:aa", "name": "Old-TV", "ip": "192.168.178.5"},
        {"mac": "bb:bb:bb:bb:bb:bb", "name": "Rogue", "ip": "192.168.178.200",
         "interface": "802.11"},
        {"mac": "cc:cc:cc:cc:cc:cc", "name": "New-but-allowed", "ip": "192.168.178.6"},
    ]
    state = {"AA:AA:AA:AA:AA:AA": now - 40 * 86400}  # 40 days old
    devs, _ = decide(samples, [1, 1, 1], state, ["cc:cc:cc:cc:cc:cc"], now=now)
    exp = NetwatchExporter()
    exp.update(devs, ok=True, new_days=7.0, now=now)
    body = exp.render().decode()
    new_lines = [ln for ln in body.splitlines() if ln.startswith("device_new{")]
    assert new_lines == [
        'device_new{connection="wifi",ip="192.168.178.200",'
        'mac="BB:BB:BB:BB:BB:BB",name="Rogue"} 1.0'
    ]
    assert "netwatch_new_total 1.0" in body
    assert 'device_known{mac="AA:AA:AA:AA:AA:AA",name="Old-TV"} 1' in body
    assert 'device_known{mac="CC:CC:CC:CC:CC:CC",name="New-but-allowed"} 1' in body


def test_annotator_transitions():
    from home_iot.annotator.exporter import OpenAnn, transitions

    # internet drops, dns fine -> one "open" for internet
    ev = transitions({"internet": 0.0, "dns": 1.0}, {})
    assert [(e.signal, e.kind) for e in ev] == [("internet", "open")]

    # internet still down (already open) -> nothing
    assert transitions({"internet": 0.0}, {"internet": OpenAnn(7, 100.0)}) == []

    # internet recovers -> "close" carrying the annotation id
    ev = transitions({"internet": 1.0}, {"internet": OpenAnn(7, 100.0)})
    assert (ev[0].signal, ev[0].kind, ev[0].ann_id) == ("internet", "close", 7)

    # query failed (None) -> ignored, no false outage
    assert transitions({"internet": None}, {}) == []


def test_annotator_config_signal_filter(monkeypatch):
    from home_iot.annotator.exporter import AnnotatorConfig

    monkeypatch.setenv("ANNOTATOR_SIGNALS", "internet, bogus ,dns")
    assert AnnotatorConfig.from_env().signals == ("internet", "dns")
    monkeypatch.setenv("ANNOTATOR_SIGNALS", "nope")
    assert AnnotatorConfig.from_env().signals == ("internet",)  # fallback


def test_bufferbloat_grade_and_summarise():
    from home_iot.bufferbloat.exporter import BufferbloatResult, grade, summarise

    assert grade(0.001) == ("A", 0.0)
    assert grade(0.02)[0] == "B"
    assert grade(0.05)[0] == "C"
    assert grade(0.15)[0] == "D"
    assert grade(0.5) == ("F", 4.0)

    s = summarise([0.010, 0.012, 0.011, 0.0, 0.050, -1.0])
    assert s["min"] == 0.010
    assert s["count"] == 4.0
    assert 0.011 <= s["p50"] <= 0.012
    assert s["p95"] == 0.050
    assert summarise([])["count"] == 0.0

    r = BufferbloatResult(idle={"p50": 0.010}, loaded_down={"p50": 0.085},
                          loaded_up={"p50": 0.010})
    assert abs(r.increase_down - 0.075) < 1e-9
    assert r.increase_up == 0.0  # clamped at 0


def test_bufferbloat_exporter_render():
    from home_iot.bufferbloat.exporter import BufferbloatExporter, BufferbloatResult

    exp = BufferbloatExporter()
    exp.update(BufferbloatResult(
        success=True,
        idle={"min": 0.008, "p50": 0.010, "p95": 0.015, "count": 12.0},
        loaded_down={"min": 0.04, "p50": 0.085, "p95": 0.12, "count": 20.0},
        loaded_up={"min": 0.02, "p50": 0.03, "p95": 0.04, "count": 20.0},
        down_mbps=240.0, up_mbps=40.0,
    ))
    body = exp.render().decode()
    assert 'bufferbloat_idle_latency_seconds{quantile="p50"} 0.01' in body
    assert "bufferbloat_increase_down_seconds 0.075" in body
    assert "bufferbloat_grade 3.0" in body  # +75ms -> D
    assert "bufferbloat_download_mbps 240.0" in body


def test_dockerstats_config_prefers_docker_host(monkeypatch):
    from home_iot.dockerstats.exporter import DockerStatsConfig

    monkeypatch.setenv("DOCKER_HOST", "tcp://proxy:2375")
    assert DockerStatsConfig.from_env().socket_path == "tcp://proxy:2375"
    monkeypatch.delenv("DOCKER_HOST")
    assert DockerStatsConfig.from_env().socket_path == "/var/run/docker.sock"


# --------------------------------------------------------------------------- #
# automation (pure rule engine)
# --------------------------------------------------------------------------- #
def test_automation_away_setback_and_restore():
    from home_iot.automation.rules import Snapshot, Tunables, evaluate

    tun = Tunables()
    away = Snapshot(occupied_now=0.0, occupied_window_max=0.0, valve_max=40.0,
                    setpoint_min=21.0, setpoint_max=21.0, lights_on=0.0)
    d = evaluate(away, {}, now=10_000.0, tun=tun)
    names = {x.rule for x in d}
    assert "away_heating_setback" in names
    setback = next(x for x in d if x.rule == "away_heating_setback")
    assert setback.action.kind == "bosch_setpoints"
    assert setback.action.params["celsius"] == tun.setback_c

    home = Snapshot(occupied_now=1.0, occupied_window_max=1.0, valve_max=0.0,
                    setpoint_min=17.0, setpoint_max=17.0, lights_on=0.0)
    d2 = evaluate(home, {}, now=10_000.0, tun=tun)
    assert {x.rule for x in d2} == {"home_heating_restore"}
    assert next(iter(d2)).action.params["celsius"] == tun.comfort_c


def test_automation_cooldown_and_missing_data():
    from home_iot.automation.rules import Snapshot, evaluate

    away = Snapshot(occupied_now=0.0, occupied_window_max=0.0, valve_max=40.0,
                    setpoint_min=21.0, setpoint_max=21.0, lights_on=2.0)
    # fired 100s ago, cooldown is 1800s -> suppressed
    d = evaluate(away, {"away_heating_setback": 9_900.0, "away_lights_off": 9_900.0},
                 now=10_000.0)
    assert "away_heating_setback" not in {x.rule for x in d}

    # all-None snapshot -> no rule fires, no crash
    assert evaluate(Snapshot(), {}, now=10_000.0) == []


def test_automation_lights_off_only_when_on():
    from home_iot.automation.rules import Snapshot, evaluate

    base = dict(occupied_now=0.0, occupied_window_max=0.0, valve_max=0.0,
                setpoint_min=21.0, setpoint_max=21.0)
    assert not [x for x in evaluate(Snapshot(lights_on=0.0, **base), {}, 10_000.0)
                if x.rule == "away_lights_off"]
    assert [x for x in evaluate(Snapshot(lights_on=3.0, **base), {}, 10_000.0)
            if x.rule == "away_lights_off"]
