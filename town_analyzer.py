# town_analyzer.py
# -*- coding: utf-8 -*-

import csv
import os
from typing import Dict, List, Optional
from town_data_manager import ensure_town_data


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(BASE_DIR, "data", "processed", "town_market_data.csv")


# =========================
# Helpers
# =========================

def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        if text == "":
            return default
        return float(text)
    except (ValueError, TypeError):
        return default


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _normalize_state(state: str) -> str:
    return (state or "").strip().upper()


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous


def _trend_label(current: float, previous: float, tolerance: float = 0.03) -> str:
    """
    tolerance=0.03 表示 ±3% 内视为 stable
    """
    if previous == 0:
        return "stable"

    change = (current - previous) / previous
    if change > tolerance:
        return "up"
    if change < -tolerance:
        return "down"
    return "stable"


# =========================
# Data Fetching / Loading
# =========================

def load_town_rows(city: str, state: str, csv_path: str = DEFAULT_DATA_FILE) -> List[Dict]:
    """
    从标准化 CSV 中读取某个 town 的所有月度记录。
    期望字段：
    month,town,state,median_sale_price,homes_sold,new_listings,inventory,days_on_market,sale_to_list_ratio,median_rent
    """
    if not os.path.exists(csv_path):
        return []

    city_key = _normalize_text(city)
    state_key = _normalize_state(state)

    rows: List[Dict] = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_city = _normalize_text(row.get("town", ""))
            row_state = _normalize_state(row.get("state", ""))

            if row_city != city_key:
                continue
            if state_key and row_state != state_key:
                continue

            rows.append({
                "month": (row.get("month") or "").strip(),
                "town": (row.get("town") or "").strip(),
                "state": (row.get("state") or "").strip(),
                "median_sale_price": _safe_float(row.get("median_sale_price")),
                "homes_sold": _safe_float(row.get("homes_sold")),
                "new_listings": _safe_float(row.get("new_listings")),
                "inventory": _safe_float(row.get("inventory")),
                "days_on_market": _safe_float(row.get("days_on_market")),
                "sale_to_list_ratio": _safe_float(row.get("sale_to_list_ratio")),
                "median_rent": _safe_float(row.get("median_rent")),
            })

    rows.sort(key=lambda x: x["month"])
    return rows


# =========================
# Calculation
# =========================

def calculate_median_price(rows: List[Dict]) -> float:
    if not rows:
        return 0.0
    return rows[-1]["median_sale_price"]


def calculate_estimated_rent(rows: List[Dict]) -> float:
    if not rows:
        return 0.0
    return rows[-1]["median_rent"]


def calculate_rent_price_ratio(median_price: float, estimated_rent: float) -> float:
    """
    月租 / 房价
    例如 3200 / 650000 = 0.00492
    """
    if median_price <= 0:
        return 0.0
    return estimated_rent / median_price


def calculate_price_trend_5y(rows: List[Dict]) -> float:
    """
    返回 5 年涨幅（如果没有 60 个月数据，就退化为“最早到最新”的涨幅）
    例如 +32% -> 0.32
    """
    if len(rows) < 2:
        return 0.0

    latest_price = rows[-1]["median_sale_price"]

    if len(rows) >= 60:
        base_price = rows[-60]["median_sale_price"]
    else:
        base_price = rows[0]["median_sale_price"]

    return _pct_change(latest_price, base_price)


def calculate_inventory_trend(rows: List[Dict]) -> str:
    """
    简单 deterministic 逻辑：
    用最近 3 个月均值 vs 一年前同月附近 3 个月均值比较。
    数据不够时，退化为最近月 vs 最早月。
    """
    if len(rows) < 2:
        return "stable"

    if len(rows) >= 15:
        recent = [r["inventory"] for r in rows[-3:]]
        past = [r["inventory"] for r in rows[-15:-12]]
        recent_avg = sum(recent) / len(recent)
        past_avg = sum(past) / len(past)
        return _trend_label(recent_avg, past_avg, tolerance=0.05)

    return _trend_label(rows[-1]["inventory"], rows[0]["inventory"], tolerance=0.05)


# =========================
# Scoring
# =========================

def score_rent_ratio(rent_price_ratio: float) -> float:
    """
    按月租售比评分，满分 4
    经验性简单规则：
    >=0.8% 很强
    >=0.6% 不错
    >=0.45% 一般
    否则偏弱
    """
    if rent_price_ratio >= 0.008:
        return 4.0
    if rent_price_ratio >= 0.006:
        return 3.0
    if rent_price_ratio >= 0.0045:
        return 2.0
    if rent_price_ratio >= 0.0035:
        return 1.0
    return 0.0


def score_appreciation(price_trend_5y: float) -> float:
    """
    5 年涨幅评分，满分 3
    """
    if price_trend_5y >= 0.50:
        return 3.0
    if price_trend_5y >= 0.30:
        return 2.5
    if price_trend_5y >= 0.15:
        return 2.0
    if price_trend_5y > 0:
        return 1.0
    return 0.0


def score_inventory(inventory_trend: str) -> float:
    """
    库存趋势评分，满分 3
    down = 供给收紧，通常更利于保值增值
    stable = 中性
    up = 偏弱
    """
    if inventory_trend == "down":
        return 3.0
    if inventory_trend == "stable":
        return 1.5
    return 0.0


def calculate_investment_score(
    rent_price_ratio: float,
    price_trend_5y: float,
    inventory_trend: str,
) -> float:
    """
    总分 10 分制
    """
    score = (
        score_rent_ratio(rent_price_ratio)
        + score_appreciation(price_trend_5y)
        + score_inventory(inventory_trend)
    )
    return round(min(score, 10.0), 1)


# =========================
# Summary Generation
# =========================

def generate_summary(
    median_price: float,
    estimated_rent: float,
    rent_price_ratio: float,
    price_trend_5y: float,
    inventory_trend: str,
    investment_score: float,
) -> str:
    parts = []

    # appreciation
    if price_trend_5y >= 0.30:
        parts.append("Strong appreciation area")
    elif price_trend_5y >= 0.10:
        parts.append("Moderate appreciation area")
    elif price_trend_5y > 0:
        parts.append("Slight appreciation area")
    else:
        parts.append("Weak appreciation area")

    # cash flow
    if rent_price_ratio >= 0.006:
        parts.append("with solid cash flow")
    elif rent_price_ratio >= 0.0045:
        parts.append("with moderate cash flow")
    else:
        parts.append("with weak cash flow")

    sentence_1 = " ".join(parts) + "."

    # inventory
    if inventory_trend == "down":
        sentence_2 = "Inventory is trending down, which supports price strength."
    elif inventory_trend == "up":
        sentence_2 = "Inventory is trending up, which may reduce pricing power."
    else:
        sentence_2 = "Inventory is relatively stable."

    # overall
    if investment_score >= 8.0:
        sentence_3 = "Suitable for long-term investment."
    elif investment_score >= 6.0:
        sentence_3 = "Reasonable market for selective investment."
    else:
        sentence_3 = "Requires caution and careful deal selection."

    return f"{sentence_1} {sentence_2} {sentence_3}"


def format_town_report(city: str, state: str, result: dict, score=None) -> str:
    """
    把 town 分析结果整理成更像“投资建议报告”的格式
    result: analyze_town() 返回的字典
    score: 可选，来自 score_town()
    """

    if not result:
        return f"❌ {city}, {state} 暂时没有可用的 town 数据。"

    # 基础字段，尽量兼容不同返回结构
    median_price = result.get("median_price", 0)
    median_rent = result.get("median_rent", 0)
    price_change_yoy = result.get("price_change_yoy", None)
    rent_change_yoy = result.get("rent_change_yoy", None)
    inventory = result.get("inventory", None)
    days_on_market = result.get("days_on_market", None)
    sale_to_list_ratio = result.get("sale_to_list_ratio", None)
    market_health = result.get("market_health", "")
    notes = result.get("notes", "")

    # 粗略估算租售比 / 年租金回报
    rent_to_price_ratio = None
    annual_gross_yield = None

    if median_price and median_rent:
        try:
            rent_to_price_ratio = round(median_rent / median_price, 4)
            annual_gross_yield = round((median_rent * 12 / median_price) * 100, 2)
        except Exception:
            pass

    # 自动生成投资判断
    strengths = []
    risks = []
    advice = []
    strategy = "需要进一步研究"

    if annual_gross_yield is not None:
        if annual_gross_yield >= 8:
            strengths.append("租金回报表现较强，现金流潜力不错")
            strategy = "偏现金流型 town"
        elif annual_gross_yield >= 6:
            strengths.append("租金回报中等，适合稳健型持有")
            strategy = "现金流和稳健持有较平衡"
        else:
            risks.append("租金回报偏弱，现金流空间可能有限")
            strategy = "更偏保值或升值逻辑，不是强现金流型"

    if price_change_yoy is not None:
        if price_change_yoy > 5:
            strengths.append("房价年增长较明显，具备一定升值潜力")
        elif price_change_yoy < 0:
            risks.append("房价同比走弱，需要留意市场转冷风险")

    if rent_change_yoy is not None:
        if rent_change_yoy > 4:
            strengths.append("租金仍在上涨，对未来收益有帮助")
        elif rent_change_yoy < 0:
            risks.append("租金同比下滑，未来租金增长可能承压")

    if days_on_market is not None:
        if days_on_market < 30:
            strengths.append("房源去化速度较快，市场活跃度不错")
        elif days_on_market > 60:
            risks.append("房源销售周期较长，流动性相对一般")

    if sale_to_list_ratio is not None:
        if sale_to_list_ratio >= 1:
            strengths.append("成交价接近或高于挂牌价，买方竞争偏强")
        elif sale_to_list_ratio < 0.97:
            risks.append("成交议价空间较大，说明市场热度一般")

    if inventory is not None:
        if inventory < 50:
            strengths.append("库存偏低，供给相对有限")
        elif inventory > 200:
            risks.append("库存偏高，短期价格承压的概率更高")

    if market_health:
        if "hot" in str(market_health).lower() or "strong" in str(market_health).lower():
            strengths.append("整体市场体感偏强")
        elif "cool" in str(market_health).lower() or "weak" in str(market_health).lower():
            risks.append("整体市场偏弱，需要更谨慎看待买入时机")

    # 行动建议
    if annual_gross_yield is not None:
        if annual_gross_yield >= 7:
            advice.append("适合继续筛选具体房源，重点看税、保险和维修后真实现金流")
        elif annual_gross_yield >= 5:
            advice.append("可以研究，但要严格挑房，避免买到税高或维护成本高的房子")
        else:
            advice.append("不建议只看 town 数据就直接进入，必须逐套核算现金流")

    if price_change_yoy is not None and price_change_yoy > 5:
        advice.append("如果你的目标偏升值，这个 town 值得继续跟踪")
    if price_change_yoy is not None and price_change_yoy < 0:
        advice.append("更适合等待更好的入场价格，不要急着追高")
    if not advice:
        advice.append("建议把这个 town 作为候选区域，再结合具体房源做二次筛选")

    # 默认补充
    if not strengths:
        strengths.append("目前没有特别突出的优势，适合作为中性候选区域观察")
    if not risks:
        risks.append("暂未看到明显硬伤，但仍需结合具体房源核算")

    # 格式化显示
    def fmt_money(v):
        if v in (None, "", 0):
            return "N/A"
        try:
            return f"${float(v):,.0f}"
        except Exception:
            return str(v)

    def fmt_pct(v):
        if v in (None, "", 0):
            return "N/A"
        try:
            return f"{float(v):.2f}%"
        except Exception:
            return str(v)

    lines = []
    lines.append(f"🏘️ {city}, {state} 投资分析报告")
    lines.append("")

    if score is not None:
        lines.append(f"⭐ 综合评分：{score}")
        lines.append("")

    lines.append("📊 市场概况")
    lines.append(f"- 中位房价：{fmt_money(median_price)}")
    lines.append(f"- 中位租金：{fmt_money(median_rent)} / 月")
    lines.append(f"- 房价同比：{fmt_pct(price_change_yoy)}")
    lines.append(f"- 租金同比：{fmt_pct(rent_change_yoy)}")
    lines.append(f"- 库存：{inventory if inventory is not None else 'N/A'}")
    lines.append(f"- 平均在市天数：{days_on_market if days_on_market is not None else 'N/A'}")
    lines.append(f"- 成交/挂牌比：{sale_to_list_ratio if sale_to_list_ratio is not None else 'N/A'}")
    lines.append("")

    lines.append("💰 投资视角")
    if annual_gross_yield is not None:
        lines.append(f"- 粗略年租金回报：{annual_gross_yield:.2f}%")
    else:
        lines.append("- 粗略年租金回报：N/A")
    lines.append(f"- 市场定位：{strategy}")
    lines.append("")

    lines.append("✅ 优势")
    for item in strengths[:3]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("⚠️ 风险")
    for item in risks[:3]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("🧭 投资建议")
    for item in advice[:3]:
        lines.append(f"- {item}")
    lines.append("")

    if notes:
        lines.append("📝 补充说明")
        lines.append(f"- {notes}")
        lines.append("")

    lines.append("👉 结论")
    if annual_gross_yield is not None and annual_gross_yield >= 7:
        conclusion = f"{city}, {state} 值得继续深入研究，尤其适合优先寻找现金流较强的出租房。"
    elif annual_gross_yield is not None and annual_gross_yield >= 5:
        conclusion = f"{city}, {state} 属于可以研究的中等机会区域，关键在于挑到合适房源。"
    else:
        conclusion = f"{city}, {state} 更适合作为备选区域观察，不建议只看 town 数据就贸然出手。"

    lines.append(conclusion)

    return "\n".join(lines)

# =========================
# Public API
# =========================

def analyze_town(city: str, state: str, csv_path: str = DEFAULT_DATA_FILE) -> dict:
    ok = ensure_town_data(city, state, csv_path=csv_path)

    if not ok:
        return {
            "median_price": 0.0,
            "estimated_rent": 0.0,
            "rent_price_ratio": 0.0,
            "price_trend_5y": 0.0,
            "inventory_trend": "stable",
            "investment_score": 0.0,
            "summary": f"目前没有 {city}, {state} 的市场数据。你可以先添加该 town 的数据，再重新分析。"
        }

    rows = load_town_rows(city, state, csv_path=csv_path)

    if not rows:
        return {
            "median_price": 0.0,
            "estimated_rent": 0.0,
            "rent_price_ratio": 0.0,
            "price_trend_5y": 0.0,
            "inventory_trend": "stable",
            "investment_score": 0.0,
            "summary": f"目前没有 {city}, {state} 的市场数据，请先添加该 town 的数据后再分析。",
        }
    median_price = calculate_median_price(rows)
    estimated_rent = calculate_estimated_rent(rows)
    rent_price_ratio = calculate_rent_price_ratio(median_price, estimated_rent)
    price_trend_5y = calculate_price_trend_5y(rows)
    inventory_trend = calculate_inventory_trend(rows)
    investment_score = calculate_investment_score(
        rent_price_ratio=rent_price_ratio,
        price_trend_5y=price_trend_5y,
        inventory_trend=inventory_trend,
    )
    summary = generate_summary(
        median_price=median_price,
        estimated_rent=estimated_rent,
        rent_price_ratio=rent_price_ratio,
        price_trend_5y=price_trend_5y,
        inventory_trend=inventory_trend,
        investment_score=investment_score,
    )

    return {
        "median_price": round(median_price, 2),
        "estimated_rent": round(estimated_rent, 2),
        "rent_price_ratio": round(rent_price_ratio, 6),
        "price_trend_5y": round(price_trend_5y, 6),
        "inventory_trend": inventory_trend,
        "investment_score": round(investment_score, 1),
        "summary": summary,
    }


# =========================
# Optional CLI test
# =========================

if __name__ == "__main__":
    city = "Princeton"
    state = "NJ"

    result = analyze_town(city, state)
    print(result)
    print()
    print(format_town_report(city, state, result))
