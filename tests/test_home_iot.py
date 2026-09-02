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
