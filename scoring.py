import re
from memory_manager import load_properties
from property_analyzer import parse_money
from utils import parse_percent

def safe_float(value, default=0.0):
    try:
        text = str(value).replace("%", "").replace("$", "").replace(",", "").strip()
        if text == "":
            return default
        return float(text)
    except (ValueError, TypeError):
        return default

def score_property_cashflow(cashflow_after_debt: float) -> float:
    if cashflow_after_debt >= 500:
        return 4.0
    if cashflow_after_debt >= 200:
        return 3.0
    if cashflow_after_debt > 0:
        return 2.0
    if cashflow_after_debt >= -200:
        return 1.0
    return 0.0

def score_property_yield(yield_percent: float) -> float:
    if yield_percent >= 8.0:
        return 4.0
    if yield_percent >= 6.0:
        return 3.0
    if yield_percent >= 4.0:
        return 2.0
    if yield_percent > 0:
        return 1.0
    return 0.0

def score_property_health(health: str) -> float:
    health = (health or "").strip()

    if health == "很強":
        return 2.0
    if health == "不錯":
        return 1.5
    if health == "一般":
        return 1.0
    return 0.0

def calculate_property_score(analysis_data: dict) -> float:
    cashflow_after_debt = safe_float(analysis_data.get("cashflow_after_debt", 0))
    yield_percent = safe_float(analysis_data.get("yield_percent", 0))
    health = analysis_data.get("health", "")

    score = (
        score_property_cashflow(cashflow_after_debt)
        + score_property_yield(yield_percent)
        + score_property_health(health)
    )

    return round(min(score, 10.0), 1)

def generate_final_decision(property_score: float, town_score: float) -> tuple[str, str]:
    final_score = round(property_score * 0.6 + town_score * 0.4, 1)

    if final_score >= 8.0:
        grade = "强烈推荐"
        decision = "这套房产本身表现较强，同时所在 town 的市场基础也不错，适合作为重点关注对象。"
    elif final_score >= 6.5:
        grade = "值得进一步研究"
        decision = "这套房产与 town 基本面整体较平衡，适合进一步核查租金真实性、维修风险和买入价格。"
    elif final_score >= 5.0:
        grade = "一般，可选择性关注"
        decision = "这套房产具备一定可投资性，但优势不够突出，更适合谨慎筛选后再决定是否推进。"
    else:
        grade = "谨慎，不建议优先投入"
        decision = "房产本身或所在 town 的支撑较弱，目前不适合作为优先投资目标。"

    return grade, decision

def final_investment_decision(analysis_data: dict, town_result: dict) -> dict:
    property_score = calculate_property_score(analysis_data)
    town_score = safe_float(town_result.get("investment_score", 0.0))

    final_score = round(property_score * 0.6 + town_score * 0.4, 1)
    grade, decision = generate_final_decision(property_score, town_score)

    return {
        "property_score": property_score,
        "town_score": round(town_score, 1),
        "final_score": final_score,
        "grade": grade,
        "decision": decision,
    }

def format_final_investment_report(result: dict) -> str:
    return (
        "最终投资结论\n\n"
        f"Property Score: {result['property_score']:.1f} / 10\n"
        f"Town Score: {result['town_score']:.1f} / 10\n"
        f"Final Score: {result['final_score']:.1f} / 10\n\n"
        f"评级：{result['grade']}\n\n"
        f"结论：\n{result['decision']}"
    )

def find_best_properties():
    properties = load_properties()

    if not properties:
        return "目前 memory 里还没有房产记录。"

    def safe_float(value):
        try:
            return float(str(value).replace("%", "").strip())
        except ValueError:
            return 0.0

    ranked = []
    for prop in properties:
        ranked.append({
            "address": prop["address"],
            "location": prop["location"],
            "final_score": safe_float(prop.get("final_score", "0")),
            "property_score": safe_float(prop.get("property_score", "0")),
            "town_score": safe_float(prop.get("town_score", "0")),
            "cashflow_after_debt": safe_float(prop.get("cashflow_after_debt", "0")),
            "yield_percent": safe_float(prop.get("yield", "0")),
            "grade": prop.get("grade", "unknown"),
            "decision": prop.get("decision", "unknown"),
        })

    ranked.sort(
        key=lambda x: (
            x["final_score"],
            x["cashflow_after_debt"],
            x["yield_percent"]
        ),
        reverse=True
    )

    if not ranked:
        return "目前没有可用于排序的房产记录。"

    lines = ["这是目前自动筛选出的最优房产排名：\n"]

    for i, prop in enumerate(ranked[:5], start=1):
        lines.append(
            f"""{i}. 地址：{prop['address']}
   地点：{prop['location']}
   Final Score：{prop['final_score']:.1f} / 10
   Property Score：{prop['property_score']:.1f} / 10
   Town Score：{prop['town_score']:.1f} / 10
   扣房贷后现金流：${prop['cashflow_after_debt']:.2f}
   年收益率：{prop['yield_percent']:.2f}%
   评级：{prop['grade']}
   结论：{prop['decision']}"""
        )

    best = ranked[0]
    lines.append(
        f"\n综合来看，目前最优先值得研究的是：{best['address']}（{best['location']}），总分 {best['final_score']:.1f} / 10。"
    )

    return "\n\n".join(lines)

def parse_deal_filters(user_text: str) -> dict:
    text = (user_text or "").strip().lower()

    filters = {
        "min_final_score": None,
        "min_cashflow": None,
        "min_yield": None,
        "min_town_score": None,
        "min_property_score": None,
        "grade_keywords": [],
        "sort_by": "final_score",
    }

    # 现金流为正
    if "现金流为正" in text or "現金流為正" in text or "正现金流" in text or "正現金流" in text:
        filters["min_cashflow"] = 0.0

    # final score
    m = re.search(r"(?:评分|分数|score)\s*(?:大于|高于|>=|＞|>)+\s*([\d\.]+)", text)
    if m:
        filters["min_final_score"] = float(m.group(1))

    # yield
    m = re.search(r"(?:yield|收益率)\s*(?:大于|高于|>=|＞|>)+\s*([\d\.]+)", text)
    if m:
        filters["min_yield"] = float(m.group(1))

    # town score
    m = re.search(r"(?:town score|town分数|town评分|town score)\s*(?:大于|高于|>=|＞|>)+\s*([\d\.]+)", text)
    if m:
        filters["min_town_score"] = float(m.group(1))

    # property score
    m = re.search(r"(?:property score|property分数|property评分)\s*(?:大于|高于|>=|＞|>)+\s*([\d\.]+)", text)
    if m:
        filters["min_property_score"] = float(m.group(1))

    # 长期投资
    if "长期投资" in text or "長期投資" in text or "长期持有" in text or "長期持有" in text:
        filters["grade_keywords"].append("长期")

    # 排序偏好
    if "现金流最高" in text or "按现金流" in text:
        filters["sort_by"] = "cashflow_after_debt"
    elif "收益率最高" in text or "按收益率" in text:
        filters["sort_by"] = "yield_percent"
    elif "town最好" in text or "town分数最高" in text:
        filters["sort_by"] = "town_score"
    else:
        filters["sort_by"] = "final_score"

    return filters

def find_deals_by_filters(user_text: str):
    properties = load_properties()

    if not properties:
        return "目前 memory 里还没有房产记录。"

    def safe_float(value):
        try:
            return float(str(value).replace("%", "").strip())
        except ValueError:
            return 0.0

    filters = parse_deal_filters(user_text)

    candidates = []
    for prop in properties:
        item = {
            "address": prop["address"],
            "location": prop["location"],
            "final_score": safe_float(prop.get("final_score", "0")),
            "property_score": safe_float(prop.get("property_score", "0")),
            "town_score": safe_float(prop.get("town_score", "0")),
            "cashflow_after_debt": safe_float(prop.get("cashflow_after_debt", "0")),
            "yield_percent": safe_float(prop.get("yield", "0")),
            "grade": prop.get("grade", "unknown"),
            "decision": prop.get("decision", "unknown"),
        }

        # 条件过滤
        if filters["min_final_score"] is not None and item["final_score"] < filters["min_final_score"]:
            continue
        if filters["min_cashflow"] is not None and item["cashflow_after_debt"] < filters["min_cashflow"]:
            continue
        if filters["min_yield"] is not None and item["yield_percent"] < filters["min_yield"]:
            continue
        if filters["min_town_score"] is not None and item["town_score"] < filters["min_town_score"]:
            continue
        if filters["min_property_score"] is not None and item["property_score"] < filters["min_property_score"]:
            continue

        if filters["grade_keywords"]:
            decision_text = (item["decision"] + " " + item["grade"]).lower()
            if "长期" in filters["grade_keywords"] and "长期" not in decision_text:
                continue

        candidates.append(item)

    if not candidates:
        return "没有找到符合条件的房产。"

    sort_by = filters["sort_by"]
    candidates.sort(
        key=lambda x: (
            x.get(sort_by, 0),
            x["final_score"],
            x["cashflow_after_debt"],
            x["yield_percent"],
        ),
        reverse=True
    )

    lines = ["条件筛选结果：\n"]

    for i, prop in enumerate(candidates[:5], start=1):
        lines.append(
            f"""{i}. 地址：{prop['address']}
   地点：{prop['location']}
   Final Score：{prop['final_score']:.1f} / 10
   Property Score：{prop['property_score']:.1f} / 10
   Town Score：{prop['town_score']:.1f} / 10
   扣房贷后现金流：${prop['cashflow_after_debt']:.2f}
   年收益率：{prop['yield_percent']:.2f}%
   评级：{prop['grade']}
   结论：{prop['decision']}"""
        )

    best = candidates[0]
    lines.append(
        f"\n最符合你当前条件的是：{best['address']}（{best['location']}）。"
    )

    return "\n\n".join(lines)

def compare_properties():
    properties = load_properties()

    if len(properties) < 2:
        return "目前至少需要两套房产记录，才能做比较。"

    def calc_net_cash_flow(prop):
        rent_num = parse_money(prop["rent"])
        hoa_num = parse_money(prop["hoa"])
        tax_num = parse_money(prop["tax"])
        insurance_num = parse_money(prop["insurance"])
        maintenance_num = parse_money(prop["maintenance"])

        vacancy_percent = 0.0
        try:
            vacancy_percent = float(prop["vacancy"])
        except ValueError:
            vacancy_percent = 0.0

        vacancy_loss = rent_num * (vacancy_percent / 100.0)
        effective_rent = rent_num - vacancy_loss
        total_cost = hoa_num + tax_num + insurance_num + maintenance_num
        net_cash_flow = effective_rent - total_cost
        return net_cash_flow

    ranked = []
    for prop in properties:
        net_cash_flow = calc_net_cash_flow(prop)
        yield_percent = parse_percent(prop["yield"])
        ranked.append({
            "address": prop["address"],
            "location": prop["location"],
            "net_cash_flow": net_cash_flow,
            "yield_percent": yield_percent,
            "health": prop["health"],
            "advice": prop["advice"],
        })

    ranked.sort(key=lambda x: (x["net_cash_flow"], x["yield_percent"]), reverse=True)

    lines = ["这是目前房产比较结果：\n"]
    for i, prop in enumerate(ranked, start=1):
        lines.append(
            f"""{i}. 地址：{prop['address']}
   地点：{prop['location']}
   每月净现金流：${prop['net_cash_flow']:.2f}
   年收益率：{prop['yield_percent']:.2f}%
   健康程度：{prop['health']}
   建议：{prop['advice']}"""
        )

    best = ranked[0]
    lines.append(
        f"\n综合来看，目前最值得继续研究的是：{best['address']}（{best['location']}）。"
    )

    return "\n\n".join(lines)

def score_town(town_analysis: dict) -> float:
    """
    简单 town 评分（先用基础版）
    """

    if not town_analysis:
        return 0

    score = 0

    # 示例逻辑（你可以按自己数据结构改）
    price = town_analysis.get("median_price", 0)
    rent = town_analysis.get("median_rent", 0)

    if price > 0 and rent > 0:
        ratio = rent * 12 / price  # 年租金 / 房价

        if ratio > 0.08:
            score += 4
        elif ratio > 0.06:
            score += 3
        elif ratio > 0.05:
            score += 2
        else:
            score += 1

    # 你可以继续加：
    # - 增长率
    # - 人口
    # - 市场热度

    return round(score, 2)
