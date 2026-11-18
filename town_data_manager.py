# town_data_manager.py
# -*- coding: utf-8 -*-

import csv
import os
import subprocess
import sys
from typing import Optional

from utils import debug, safe_float, parse_percent, parse_city_state, xml_escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(BASE_DIR, "data", "processed", "town_market_data.csv")
FETCH_SCRIPT = os.path.join(BASE_DIR, "fetch_redfin_data.py")


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def normalize_state(state: str) -> str:
    return (state or "").strip().upper()


def has_town_data(city: str, state: str, csv_path: str = DEFAULT_DATA_FILE) -> bool:
    """
    检查本地 town_market_data.csv 是否已有该 town 数据
    """
    if not os.path.exists(csv_path):
        return False

    city_key = normalize_text(city)
    state_key = normalize_state(state)

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_city = normalize_text(row.get("town", ""))
            row_state = normalize_state(row.get("state", ""))

            if row_city == city_key and row_state == state_key:
                return True

    return False


def fetch_missing_town_data(city: str, state: str, timeout: int = 120) -> bool:
    """
    调用 fetch_redfin_data.py 抓指定 town 的数据
    """
    if not os.path.exists(FETCH_SCRIPT):
        print(f"[DEBUG] fetch script not found: {FETCH_SCRIPT}")
        return False

    cmd = [
        sys.executable,
        FETCH_SCRIPT,
        "--town", city,
        "--state", state,
        "--download-first",
    ]

    debug("Running fetch command:", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        debug("fetch stdout:\n", result.stdout)
        debug("fetch stderr:\n", result.stderr)

        if result.returncode != 0:
            return False

        if not has_town_data(city, state):
            debug("fetch returned 0 but data not found")
            return False

    except subprocess.TimeoutExpired:
        debug("fetch timed out")
        return False
    except Exception as e:
        debug("fetch failed:", repr(e))
        return False


def ensure_town_data(city: str, state: str, csv_path: str = DEFAULT_DATA_FILE) -> bool:
    if not city or not state:
        return False

    city_key = normalize_text(city)
    state_key = normalize_state(state)

    if has_town_data(city_key, state_key, csv_path):
        print(f"[DEBUG] Local cache hit for {city}, {state}")
        return True

    print(f"[DEBUG] Local cache miss for {city}, {state}, fetching...")
    ok = fetch_missing_town_data(city, state)

    if not ok:
        return False

    # 👉 再检查一次（必要）
    return has_town_data(city_key, state_key, csv_path)
