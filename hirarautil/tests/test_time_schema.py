"""time_now, date_calc and schema_validate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hirarautil.config import UtilConfig
from hirarautil.timecalc import date_calc, time_now
from hirarautil.tools import Toolset

NOW = datetime(2026, 10, 23, 15, 30, tzinfo=timezone.utc)  # a Friday


@pytest.fixture
def ts():
    return Toolset(UtilConfig())


def test_time_now_zones():
    r = time_now(["UTC", "Asia/Yangon", "America/New_York"], now=NOW)
    yangon = r["zones"][1]
    assert yangon["time"] == "22:00:00" and yangon["utc_offset"] == "+06:30"
    ny = r["zones"][2]
    assert ny["date"] == "2026-10-23" and ny["dst"] is True and ny["utc_offset"] == "-04:00"
    assert r["zones"][0]["weekday"] == "Friday"


async def test_time_now_tool_and_bad_zone(ts):
    r = await ts.time_now()
    assert r["error"] is None and r["zones"][0]["timezone"] == "UTC"
    r = await ts.time_now(timezones="Asia/Rangoon_typo")
    assert "unknown time zone" in r["error"]


def test_add_months_clamps_and_business_days():
    r = date_calc("add", date_value="2026-01-31", months=1, now=NOW)
    assert r["result"]["date"] == "2026-02-28"
    r = date_calc("add", date_value="2024-01-31", months=1, now=NOW)
    assert r["result"]["date"] == "2024-02-29"
    r = date_calc("add", date_value="2026-10-23", business_days=1, now=NOW)  # Fri -> Mon
    assert r["result"]["date"] == "2026-10-26"
    r = date_calc("add", date_value="2026-10-23", business_days=3, holidays=["2026-10-26"], now=NOW)
    assert r["result"]["date"] == "2026-10-29"


def test_add_across_dst_keeps_wall_clock_for_days():
    # US DST ends 2026-11-01: +1 day keeps 09:00, +24 hours does not.
    r = date_calc("add", date_value="2026-10-31T09:00", timezone_name="America/New_York",
                  days=1, now=NOW)
    assert r["result"]["time"] == "09:00:00"
    r = date_calc("add", date_value="2026-10-31T09:00", timezone_name="America/New_York",
                  hours=24, now=NOW)
    assert r["result"]["time"] == "08:00:00"


def test_diff_calendar_and_business():
    r = date_calc("diff", date_value="2026-01-15", other="2027-03-20", now=NOW)
    assert r["result"]["calendar"]["years"] == 1
    assert r["result"]["calendar"]["months"] == 2
    assert r["result"]["calendar"]["days"] == 5
    r = date_calc("diff", date_value="2026-10-19", other="2026-11-02", now=NOW)  # Mon..Mon
    assert r["result"]["business_days"] == 10
    r = date_calc("diff", date_value="2026-11-02", other="2026-10-19", now=NOW)
    assert r["result"]["business_days"] == -10
    r = date_calc("diff", date_value="2026-10-18", other="2026-10-25", weekend=["fri", "sat"],
                  now=NOW)
    assert r["result"]["business_days"] == 5


def test_convert_info_and_words():
    r = date_calc("convert", date_value="2026-10-23T09:00", timezone_name="Asia/Yangon",
                  to_timezones=["Europe/London", "UTC"], now=NOW)
    assert [z["time"] for z in r["result"]] == ["03:30:00", "02:30:00"]
    r = date_calc("info", date_value="2028-02-10", now=NOW)
    assert r["result"]["is_leap_year"] and r["result"]["days_in_month"] == 29
    assert r["result"]["week_start"] == "2028-02-07"
    r = date_calc("info", date_value="tomorrow", now=NOW)
    assert r["result"]["date"] == "2026-10-24" and r["result"]["is_business_day"] is False


async def test_date_calc_errors(ts):
    r = await ts.date_calc(operation="diff", date="2026-01-01")
    assert "needs other" in r["error"]
    r = await ts.date_calc(operation="add", date="31/12/2026")
    assert "ISO 8601" in r["error"]
    r = await ts.date_calc(operation="explode")
    assert "operation must be" in r["error"]
    r = await ts.date_calc(operation="add", date="9999-12-31", years=1)
    assert r["error"]


SCHEMA = {
    "type": "object",
    "required": ["name", "tags"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "email": {"type": "string", "format": "email"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


async def test_schema_validate_reports_every_error(ts):
    r = await ts.schema_validate(instance={"name": "", "tags": ["a", 2], "x": 1, "email": "nope"},
                                 schema=SCHEMA)
    assert r["error"] is None and r["valid"] is False
    paths = {e["path"] for e in r["errors"]}
    assert {"/name", "/tags/1", "/email", ""} <= paths
    r = await ts.schema_validate(instance='{"name": "a", "tags": []}', schema=SCHEMA)
    assert r["valid"] is True and r["draft"] == "Draft202012"


async def test_schema_validate_bad_inputs(ts):
    r = await ts.schema_validate(instance="{bad", schema=SCHEMA)
    assert "instance is not valid JSON" in r["error"]
    r = await ts.schema_validate(instance={}, schema={"type": "nonsense"})
    assert "schema itself is invalid" in r["error"]
    r = await ts.schema_validate(instance={}, schema={"$schema": "http://json-schema.org/draft-07/schema#",
                                                      "type": "object"})
    assert r["draft"] == "Draft7"
