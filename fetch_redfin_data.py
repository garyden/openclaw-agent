#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetch_redfin_data.py

从 Redfin Data Center 的公开月度市场数据中抓取 city 级别数据，
筛选指定的 town/city，输出到你的项目可直接使用的：
    data/processed/town_market_data.csv

默认输出字段：
    month,town,state,median_sale_price,homes_sold,new_listings,inventory,
    days_on_market,sale_to_list_ratio,median_rent

特点：
1. 不依赖 API key。
2. 优先读取 Redfin 城市级月度文件。
3. 对 Redfin 字段名做了“候选名映射”，尽量兼容将来的轻微变动。
4. 支持命令行传入多个 town。
5. 如果没有租金字段，会把 median_rent 留空。

示例：
    python fetch_redfin_data.py --town Princeton --state NJ

    python fetch_redfin_data.py \
        --town Princeton --town Edison --town "West Windsor" \
        --state NJ

可选：
    python fetch_redfin_data.py --config towns.json

其中 towns.json 示例：
{
  "state": "NJ",
  "towns": ["Princeton", "Edison", "West Windsor"]
}
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests

# Redfin Data Center monthly city-level data URL.
# Redfin Data Center page currently links city monthly data from the public S3 bucket.
REDFIN_CITY_URL = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_market_tracker/city_market_tracker.tsv000.gz"
)

# 你的项目默认输出位置
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "data" / "processed" / "town_market_data.csv"
DEFAULT_CACHE_DIR = BASE_DIR / "data" / "raw"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "redfin_city_market_tracker.tsv000.gz"


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_state(value: object) -> str:
    return str(value or "").strip().upper()


def first_existing_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        real = lower_map.get(candidate.lower())
        if real:
            return real
    return None


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def download_redfin_file(url: str, cache_path: Path, timeout: int = 120) -> Path:
    ensure_parent_dir(cache_path)
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    with cache_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return cache_path


def load_redfin_city_data(source: str, towns: list[str], state: str) -> pd.DataFrame:
    """
    只读取目标 town，避免全量加载大文件
    """

    if source == "remote":
        path = REDFIN_CITY_URL
        compression = "gzip"
    else:
        path = source
        compression = "gzip" if str(source).endswith(".gz") else "infer"

    chunks = pd.read_csv(
        path,
        sep="\t",
        compression=compression,
        chunksize=50000,   # 🔥 关键
        low_memory=False,
    )

    matched = []

    town_keys = {normalize_text(t) for t in towns}
    state_key = normalize_state(state)

    for i, chunk in enumerate(chunks, start=1):
        print(f"[2/4] 处理 chunk {i}...")

        # 找列名（只需要一次）
        if i == 1:
            column_map = map_redfin_columns(chunk)

        town_col = column_map["town"]
        state_col = column_map["state"]

        if not town_col or not state_col:
            continue

        chunk[town_col] = chunk[town_col].astype(str).map(normalize_text)
        chunk[state_col] = chunk[state_col].astype(str).map(normalize_state)

        filtered = chunk[
            (chunk[town_col].isin(town_keys)) &
            (chunk[state_col] == state_key)
        ]

        if not filtered.empty:
            matched.append(filtered)

    if matched:
        return pd.concat(matched, ignore_index=True)

    return pd.DataFrame()


def coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def map_redfin_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    针对 Redfin 常见 schema 做字段候选映射。
    这里故意写得宽一点，避免小改版就挂掉。
    """
    return {
        "period_begin": first_existing_column(df, ["period_begin", "period_begin_date"]),
        "period_end": first_existing_column(df, ["period_end"]),
        "region_type": first_existing_column(df, ["region_type"]),
        "town": first_existing_column(df, ["city", "region", "region_name"]),
        "state": first_existing_column(df, ["state_code", "state"]),
        "property_type": first_existing_column(df, ["property_type"]),
        "seasonal": first_existing_column(df, ["is_seasonally_adjusted"]),
        "median_sale_price": first_existing_column(df, ["median_sale_price"]),
        "homes_sold": first_existing_column(df, ["homes_sold", "home_sales"]),
        "new_listings": first_existing_column(df, ["new_listings"]),
        "inventory": first_existing_column(df, ["inventory", "active_listings"]),
        "median_dom": first_existing_column(df, ["median_dom", "median_days_on_market"]),
        "sale_to_list_ratio": first_existing_column(df, ["avg_sale_to_list", "median_sale_to_list", "sale_to_list_ratio"]),
        "median_rent": first_existing_column(df, ["median_rent"]),
        "last_updated": first_existing_column(df, ["last_updated"]),
    }


def filter_city_monthly_rows(
    df: pd.DataFrame,
    column_map: Dict[str, Optional[str]],
    towns: Sequence[str],
    state: str,
    property_type: str = "All Residential",
    seasonally_adjusted: bool = False,
) -> pd.DataFrame:
    out = df.copy()
    print(f"[DEBUG] initial rows: {len(out):,}")

    # region_type == city / place
    region_col = column_map["region_type"]
    if region_col:
        print("[DEBUG] region_type unique sample:", out[region_col].dropna().astype(str).value_counts().head(10).to_dict())
        allowed_region_types = {"city", "place"}
        out = out[out[region_col].astype(str).str.lower().isin(allowed_region_types)]
        print(f"[DEBUG] after region_type filter: {len(out):,}")

    # state filter
    state_col = column_map["state"]
    if state and state_col:
        print("[DEBUG] state unique sample:", out[state_col].dropna().astype(str).value_counts().head(10).to_dict())
        out = out[out[state_col].astype(str).str.upper() == state.upper()]
        print(f"[DEBUG] after state filter: {len(out):,}")

    # property_type filter
    property_type_col = column_map["property_type"]
    if property_type and property_type_col:
        print("[DEBUG] property_type unique sample:", out[property_type_col].dropna().astype(str).value_counts().head(10).to_dict())
        out = out[out[property_type_col].astype(str).str.lower() == property_type.lower()]
        print(f"[DEBUG] after property_type filter: {len(out):,}")

    # seasonality filter
    seasonal_col = column_map["seasonal"]
    if seasonal_col:
        print("[DEBUG] seasonal unique sample:", out[seasonal_col].dropna().astype(str).value_counts().head(10).to_dict())
        if seasonally_adjusted:
            out = out[out[seasonal_col].astype(str).str.lower().isin(["true", "1"])]
        else:
            out = out[out[seasonal_col].astype(str).str.lower().isin(["false", "0"])]
        print(f"[DEBUG] after seasonal filter: {len(out):,}")

    # town filter
    town_col = column_map["town"]
    if not town_col:
        raise KeyError("Redfin 数据里没有找到 town/city 对应列。")

    print("[DEBUG] town sample:", out[town_col].dropna().astype(str).head(20).tolist())
    wanted = {normalize_text(t) for t in towns}
    print("[DEBUG] wanted towns:", wanted)

    out = out[out[town_col].map(normalize_text).isin(wanted)]
    print(f"[DEBUG] after town filter: {len(out):,}")

    return out


def transform_for_town_analyzer(df: pd.DataFrame, column_map: Dict[str, Optional[str]]) -> pd.DataFrame:
    def col(name: str) -> Optional[pd.Series]:
        real = column_map.get(name)
        if real and real in df.columns:
            return df[real]
        return None

    # 月份：优先用 period_begin -> YYYY-MM
    if col("period_begin") is not None:
        month = pd.to_datetime(col("period_begin"), errors="coerce").dt.to_period("M").astype(str)
    elif col("period_end") is not None:
        month = pd.to_datetime(col("period_end"), errors="coerce").dt.to_period("M").astype(str)
    else:
        raise KeyError("Redfin 数据里没有找到 period_begin / period_end。")

    town_series = col("town")
    state_series = col("state")
    if town_series is None or state_series is None:
        raise KeyError("Redfin 数据里没有找到 city/state 列。")

    out = pd.DataFrame(
        {
            "month": month,
            "town": town_series.astype(str).str.strip(),
            "state": state_series.astype(str).str.upper().str.strip(),
            "median_sale_price": coerce_numeric(col("median_sale_price")) if col("median_sale_price") is not None else pd.NA,
            "homes_sold": coerce_numeric(col("homes_sold")) if col("homes_sold") is not None else pd.NA,
            "new_listings": coerce_numeric(col("new_listings")) if col("new_listings") is not None else pd.NA,
            "inventory": coerce_numeric(col("inventory")) if col("inventory") is not None else pd.NA,
            "days_on_market": coerce_numeric(col("median_dom")) if col("median_dom") is not None else pd.NA,
            "sale_to_list_ratio": coerce_numeric(col("sale_to_list_ratio")) if col("sale_to_list_ratio") is not None else pd.NA,
            "median_rent": coerce_numeric(col("median_rent")) if col("median_rent") is not None else pd.NA,
        }
    )

    # 清掉无 month 的行
    out = out[out["month"].notna()].copy()

    # 排序并去重（同月/同城市保留最后一行）
    out = out.sort_values(["state", "town", "month"]).drop_duplicates(
        subset=["state", "town", "month"], keep="last"
    )

    return out


def merge_with_existing(existing_path: Path, new_df: pd.DataFrame) -> pd.DataFrame:
    if not existing_path.exists():
        return new_df.copy()

    old_df = pd.read_csv(existing_path)
    combined = pd.concat([old_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["month", "town", "state"], keep="last")
    combined = combined.sort_values(["state", "town", "month"])
    return combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取并转换 Redfin 城市级月度市场数据")
    parser.add_argument("--town", action="append", dest="towns", help="可重复传入多个 town，如 --town Princeton --town Edison")
    parser.add_argument("--state", default="", help="州缩写，如 NJ")
    parser.add_argument("--config", help="JSON 配置文件，格式见脚本头部说明")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 CSV 路径")
    parser.add_argument(
        "--source",
        default="remote",
        help="数据来源：remote 或本地 .tsv/.tsv.gz 文件路径",
    )
    parser.add_argument(
        "--download-first",
        action="store_true",
        help="先下载到本地 cache，再从本地读取。网络不稳时更容易排错。",
    )
    parser.add_argument(
        "--cache-file",
        default=str(DEFAULT_CACHE_FILE),
        help="download-first 时保存的本地原始文件路径",
    )
    parser.add_argument(
        "--property-type",
        default="All Residential",
        help='Redfin property_type 过滤，默认 "All Residential"',
    )
    parser.add_argument(
        "--seasonally-adjusted",
        action="store_true",
        help="抓取季调数据；默认抓未季调数据。",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="直接覆盖输出文件；默认会和旧文件按 month/town/state 合并去重。",
    )
    return parser.parse_args()


def load_config(config_path: Optional[str]) -> Tuple[List[str], str]:
    if not config_path:
        return [], ""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    towns = [str(x).strip() for x in data.get("towns", []) if str(x).strip()]
    state = str(data.get("state", "")).strip().upper()
    return towns, state


def main() -> int:
    args = parse_args()

    config_towns, config_state = load_config(args.config)
    towns = list(dict.fromkeys((args.towns or []) + config_towns))
    state = (args.state or config_state or "").strip().upper()

    if not towns:
        print("错误：请至少提供一个 --town，或在 --config 里提供 towns。", file=sys.stderr)
        return 2

    source = args.source
    if args.download_first:
        cache_file = Path(args.cache_file)
        print(f"[1/4] 下载 Redfin 原始数据到: {cache_file}")
        if not cache_file.exists():
            download_redfin_file(REDFIN_CITY_URL, cache_file)
        else:
            print("使用本地缓存")
        source = str(cache_file)

    print(f"[2/4] 读取数据源: {source}")
    df = load_redfin_city_data(source, towns, state)
    print(f"     原始数据行数: {len(df):,}")

    print("[3/4] 字段映射与筛选")
    column_map = map_redfin_columns(df)
    missing_hard_requirements = [
        k for k in ["period_begin", "town", "state", "median_sale_price", "homes_sold", "inventory", "median_dom", "sale_to_list_ratio"]
        if column_map.get(k) is None
    ]
    if missing_hard_requirements:
        print("警告：以下关键字段未在当前数据中找到：", ", ".join(missing_hard_requirements), file=sys.stderr)
        print("当前识别到的列名：", file=sys.stderr)
        print(df.columns.tolist(), file=sys.stderr)

    filtered = filter_city_monthly_rows(
        df=df,
        column_map=column_map,
        towns=towns,
        state=state,
        #property_type=args.property_type,
        property_type="",
        seasonally_adjusted=args.seasonally_adjusted,
    )
    print(f"     筛选后行数: {len(filtered):,}")

    if filtered.empty:
        print("没有找到匹配的 city 数据。", file=sys.stderr)
        print(f"towns={towns}, state={state}, property_type={args.property_type}", file=sys.stderr)
        return 1

    transformed = transform_for_town_analyzer(filtered, column_map)

    output_path = Path(args.output)
    ensure_parent_dir(output_path)

    print(f"[4/4] 写入输出: {output_path}")
    final_df = transformed if args.replace else merge_with_existing(output_path, transformed)
    final_df.to_csv(output_path, index=False)

    # 简短摘要
    print("完成。输出预览：")
    print(final_df.tail(min(10, len(final_df))).to_string(index=False))
    print(f"\n共写入 {len(final_df):,} 行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
