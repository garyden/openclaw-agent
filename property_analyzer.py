import re
from utils import parse_city_state, debug

def extract_house_info(user_text):
    def find_value(pattern):
        match = re.search(pattern, user_text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    info = {
        "address": find_value(r"地址[:：]\s*([^\n]+)"),
        "price": find_value(r"价格[:：]\s*([$\d,\.kK]+)"),
        "size": find_value(r"(?:面积|size)[:：]\s*([^\n]+)"),
        "rent": find_value(r"(?:租金|rent)[:：]\s*([$\d,\.kK]+)"),
        "location": find_value(r"(?:地点|地點|location)[:：]\s*(.+)"),
        "hoa": find_value(r"HOA[:：]\s*([$\d,\.kK]+)"),
        "tax": find_value(r"(?:地税|地稅|tax)[:：]\s*([$\d,\.kK]+)"),
        "insurance": find_value(r"(?:保险|保險|insurance)[:：]\s*([$\d,\.kK]+)"),
        "maintenance": find_value(r"(?:维修|維修|maintenance)[:：]\s*([$\d,\.kK]+)"),
        "vacancy": find_value(r"(?:空置率|vacancy)[:：]\s*([\d\.]+)"),
        "down_payment": find_value(r"(?:首付|down payment)[:：]\s*([\d\.]+)"),
        "interest_rate": find_value(r"(?:利率|interest rate)[:：]\s*([\d\.]+)"),
        "loan_years": find_value(r"(?:貸款年限|贷款年限|loan years)[:：]\s*([\d\.]+)")
    }

    # 新增：如果没提供 location，就从 address 推断
    if not info["location"] and info["address"] and "," in info["address"]:
        parts = [p.strip() for p in info["address"].split(",")]

        if len(parts) >= 3:
            city = parts[-2]

            # 只取 state 的前两个字符（NJ / CA / TX）
            state_part = parts[-1].split()[0].upper()

            info["location"] = f"{city}, {state_part}"

        elif len(parts) == 2:
            state_part = parts[-1].split()[0].upper()
            info["location"] = state_part

    return info

def parse_money(value):
    if not value:
        return 0.0

    value = value.replace("$", "").replace(",", "").strip().lower()

    if value.endswith("k"):
        return float(value[:-1]) * 1000

    try:
        return float(value)
    except ValueError:
        return 0.0

def auto_extract_house_info(raw_text):
    def find_first(patterns):
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    address = find_first([
        r"(?m)^([0-9]{1,6}\s+.+?,\s*.+?,\s*[A-Z]{2})$",
        r"(?m)^([0-9]{1,6}\s+.+)$",
    ])

    price = find_first([
        r"\$([\d,]+)",
        r"price[:：]?\s*\$?([\d,]+)",
    ])

    size = find_first([
        r"([\d,]+)\s*sqft",
        r"(?:面积|面積|size)[:：]?\s*([^\n]+)",
    ])

    rent = find_first([
        r"(?:rent|estimated rent)[^\d\$]*\$([\d,]+)",
        r"(?:租金)[:：]?\s*\$?([\d,]+)",
    ])

    hoa = find_first([
        r"HOA[^\d\$]*\$([\d,]+)",
    ])

    tax = find_first([
        r"(?:property tax|tax)[^\d\$]*\$([\d,]+)",
        r"(?:地税|地稅)[^\d\$]*\$?([\d,]+)",
    ])

    insurance = find_first([
        r"(?:insurance)[^\d\$]*\$([\d,]+)",
        r"(?:保险|保險)[^\d\$]*\$?([\d,]+)",
    ])

    maintenance = find_first([
        r"(?:maintenance)[^\d\$]*\$([\d,]+)",
        r"(?:维修|維修)[^\d\$]*\$?([\d,]+)",
    ])

    vacancy = find_first([
        r"(?:vacancy)[^\d]*([\d\.]+)%",
        r"(?:空置率)[^\d]*([\d\.]+)",
    ])

    down_payment = find_first([
        r"(?:down payment|dp)[^\d]*([\d\.]+)",
        r"(?:首付)[^\d]*([\d\.]+)",
    ])

    interest_rate = find_first([
        r"(?:interest rate|rate)[^\d]*([\d\.]+)",
        r"(?:利率)[^\d]*([\d\.]+)",
    ])

    loan_years = find_first([
        r"(?:loan years|yr|years)[^\d]*([\d\.]+)",
        r"(?:貸款年限|贷款年限)[^\d]*([\d\.]+)",
    ])

    location = ""
    if address and "," in address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            location = parts[-1] if len(parts) == 2 else f"{parts[-2]}, {parts[-1]}"

    return {
        "address": address,
        "price": price,
        "size": size,
        "rent": rent,
        "location": location,
        "hoa": hoa,
        "tax": tax,
        "insurance": insurance,
        "maintenance": maintenance,
        "vacancy": vacancy,
        "down_payment": down_payment,
        "interest_rate": interest_rate,
        "loan_years": loan_years,
    }

def normalize_to_analysis_text(info):
    return f"""分析這個房子：
地址：{info.get('address', '')}
價格：{info.get('price', '')}
面積：{info.get('size', '')}
租金：{info.get('rent', '')}
地點：{info.get('location', '')}
HOA：{info.get('hoa', '')}
地稅：{info.get('tax', '')}
保險：{info.get('insurance', '')}
維修：{info.get('maintenance', '')}
空置率：{info.get('vacancy', '')}
首付：{info.get('down_payment', '')}
利率：{info.get('interest_rate', '')}
貸款年限：{info.get('loan_years', '')}
"""

def analyze_house(user_text):
    info = extract_house_info(user_text)

    debug(info)

    price_num = parse_money(info["price"])
    rent_num = parse_money(info["rent"])
    hoa_num = parse_money(info["hoa"])
    tax_num = parse_money(info["tax"])
    insurance_num = parse_money(info["insurance"])
    maintenance_num = parse_money(info["maintenance"])

    vacancy_percent = float(info["vacancy"]) if info["vacancy"] else 0.0
    vacancy_loss = rent_num * (vacancy_percent / 100.0)

    effective_rent = rent_num - vacancy_loss
    total_monthly_cost = hoa_num + tax_num + insurance_num + maintenance_num

    down_payment_percent = float(info["down_payment"]) if info["down_payment"] else 100.0
    interest_rate = float(info["interest_rate"]) if info["interest_rate"] else 0.0
    loan_years = int(float(info["loan_years"])) if info["loan_years"] else 0

    loan_amount = price_num * (1 - down_payment_percent / 100.0)
    monthly_mortgage = calculate_monthly_mortgage(loan_amount, interest_rate, loan_years)

    net_cash_flow_before_debt = effective_rent - total_monthly_cost
    net_cash_flow_after_debt = net_cash_flow_before_debt - monthly_mortgage

    monthly_ratio = (rent_num / price_num) if price_num > 0 else 0
    annual_gross_yield = ((rent_num * 12) / price_num) if price_num > 0 else 0
    annual_net_yield = ((net_cash_flow_before_debt * 12) / price_num) if price_num > 0 else 0

    ratio_percent = monthly_ratio * 100
    gross_yield_percent = annual_gross_yield * 100
    net_yield_percent = annual_net_yield * 100

    if net_cash_flow_after_debt > 500:
        health = "很強"
        advice = "扣除房貸後仍有不錯現金流，值得進一步研究。"
    elif net_cash_flow_after_debt > 0:
        health = "不錯"
        advice = "扣除房貸後仍為正現金流，但安全邊際不算大。"
    elif net_cash_flow_after_debt > -300:
        health = "一般"
        advice = "接近打平，對租金、空置率和維修很敏感。"
    else:
        health = "偏弱"
        advice = "扣除房貸後現金流偏弱，投資上需要很謹慎。"

    analysis_text = f"""房產槓桿現金流分析

地址：{info['address'] or '未提供'}
地點：{info['location'] or '未提供'}
價格：{info['price'] or '未提供'}
面積：{info['size'] or '未提供'}
月租金：{info['rent'] or '未提供'}

附加成本
HOA：{info['hoa'] or '0'}
地稅：{info['tax'] or '0'}
保險：{info['insurance'] or '0'}
維修：{info['maintenance'] or '0'}
空置率：{info['vacancy'] or '0'}%

貸款條件
首付：{info['down_payment'] or '100'}%
利率：{info['interest_rate'] or '0'}%
貸款年限：{info['loan_years'] or '0'} 年

1. 基礎指標
租售比 = {ratio_percent:.2f}%
年毛收益率 = {gross_yield_percent:.2f}%
年淨收益率（未扣房貸） = {net_yield_percent:.2f}%

2. 現金流（未扣房貸）
空置損失 = ${vacancy_loss:.2f}
有效月租金 = ${effective_rent:.2f}
每月固定支出 = ${total_monthly_cost:.2f}
每月淨現金流（未扣房貸） = ${net_cash_flow_before_debt:.2f}

3. 槓桿分析
貸款金額 = ${loan_amount:.2f}
每月房貸 = ${monthly_mortgage:.2f}
每月淨現金流（扣房貸後） = ${net_cash_flow_after_debt:.2f}

4. 健康程度
{health}

5. 建議
{advice}

6. 風險點
- 利率變化會直接影響現金流
- 尚未計入物業管理費與大修資本支出
- 實際租金與空置率可能與預估不同
"""

    analysis_data = {
        "ratio_percent": f"{ratio_percent:.2f}%",
        "yield_percent": f"{gross_yield_percent:.2f}%",
        "health": health,
        "advice": advice,
        "loan_amount": f"{loan_amount:.2f}",
        "monthly_mortgage": f"{monthly_mortgage:.2f}",
        "cashflow_after_debt": f"{net_cash_flow_after_debt:.2f}",
    }

    return analysis_text, info, analysis_data

def calculate_monthly_mortgage(principal, annual_rate, years):
    if principal <= 0 or annual_rate <= 0 or years <= 0:
        return 0.0

    monthly_rate = annual_rate / 100 / 12
    num_payments = years * 12

    payment = principal * (
        monthly_rate * (1 + monthly_rate) ** num_payments
    ) / (
        (1 + monthly_rate) ** num_payments - 1
    )

    return payment
