import os
import re
from utils import xml_escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "memory", "memory.xml")

def ensure_memory_file():
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write("""<memory>
    <user>
        <name></name>
        <language>zh</language>
    </user>
    <facts>
    </facts>
    <preferences>
    </preferences>
    <history>
    </history>
    <properties>
    </properties>
</memory>""")
        return

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    changed = False

    if "<facts>" not in content:
        content = content.replace("</user>", "</user>\n    <facts>\n    </facts>")
        changed = True

    if "<preferences>" not in content:
        content = content.replace("</facts>", "</facts>\n    <preferences>\n    </preferences>")
        changed = True

    if "<history>" not in content:
        content = content.replace("</preferences>", "</preferences>\n    <history>\n    </history>")
        changed = True

    if "<properties>" not in content:
        content = content.replace("</history>", "</history>\n    <properties>\n    </properties>")
        changed = True

    if changed:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(content)

def load_memory():
    ensure_memory_file()
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f.read()

def append_fact(text):
    ensure_memory_file()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    new_fact = f"        <fact>{text}</fact>\n"
    if "</facts>" in content:
        content = content.replace("</facts>", new_fact + "    </facts>")

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def delete_property(address):
    ensure_memory_file()

    if not address or not address.strip():
        return False, "没有提供房产地址。"

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    properties_match = re.search(r"<properties>(.*?)</properties>", content, re.DOTALL)
    if not properties_match:
        return False, "memory 里没有 properties 区块。"

    properties_inner = properties_match.group(1)
    property_blocks = re.findall(r"<property>(.*?)</property>", properties_inner, re.DOTALL)

    if not property_blocks:
        return False, "目前 memory 里还没有房产记录。"

    target = address.strip().lower()

    def extract_address(block):
        match = re.search(r"<address>(.*?)</address>", block, re.DOTALL)
        return match.group(1).strip() if match else ""

    exact_matches = []
    partial_matches = []

    for block in property_blocks:
        block_address = extract_address(block)
        normalized = block_address.lower()

        if normalized == target:
            exact_matches.append((block, block_address))
        elif target in normalized:
            partial_matches.append((block, block_address))

    # 优先精确匹配
    if len(exact_matches) == 1:
        block_to_delete, matched_address = exact_matches[0]
    elif len(exact_matches) > 1:
        matched_list = "\n".join([f"- {addr}" for _, addr in exact_matches])
        return False, f"找到多套完全匹配的房产，请提供更完整地址：\n{matched_list}"
    elif len(partial_matches) == 1:
        block_to_delete, matched_address = partial_matches[0]
    elif len(partial_matches) > 1:
        matched_list = "\n".join([f"- {addr}" for _, addr in partial_matches])
        return False, f"找到多套包含关键词「{address}」的房产，请提供更完整地址：\n{matched_list}"
    else:
        return False, f"没有找到包含地址关键词「{address}」的房产。"

    updated_blocks = []
    for block in property_blocks:
        if block == block_to_delete:
            continue
        updated_blocks.append(block)

    new_properties_section = "    <properties>\n"
    for block in updated_blocks:
        new_properties_section += "        <property>" + block + "</property>\n"
    new_properties_section += "    </properties>"

    content = re.sub(
        r"<properties>.*?</properties>",
        new_properties_section,
        content,
        flags=re.DOTALL
    )

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    return True, f"已删除房产：{matched_address}"

def append_preference(text):
    ensure_memory_file()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    new_pref = f"        <preference>{text}</preference>\n"
    if "</preferences>" in content:
        content = content.replace("</preferences>", new_pref + "    </preferences>")

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def append_property(
    address,
    price,
    size,
    rent,
    location,
    ratio_percent="",
    yield_percent="",
    health="",
    advice="",
    hoa="",
    tax="",
    insurance="",
    maintenance="",
    vacancy="",
    loan_amount="",
    monthly_mortgage="",
    cashflow_after_debt="",
    property_score="",
    town_score="",
    final_score="",
    grade="",
    decision="",
):
    ensure_memory_file()

    address_key = " ".join((address or "").lower().strip().split())
    if property_exists(address_key):
        return False

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    new_property = f"""        <property>
            <address>{xml_escape(address_key) or 'unknown'}</address>
            <price>{xml_escape(price) or 'unknown'}</price>
            <size>{xml_escape(size) or 'unknown'}</size>
            <rent>{xml_escape(rent) or 'unknown'}</rent>
            <location>{xml_escape(location) or 'unknown'}</location>
            <hoa>{hoa or '0'}</hoa>
            <tax>{tax or '0'}</tax>
            <insurance>{insurance or '0'}</insurance>
            <maintenance>{maintenance or '0'}</maintenance>
            <vacancy>{vacancy or '0'}</vacancy>
            <ratio>{ratio_percent or 'unknown'}</ratio>
            <yield>{yield_percent or 'unknown'}</yield>
            <health>{xml_escape(health) or 'unknown'}</health>
            <advice>{xml_escape(advice) or 'unknown'}</advice>
            <loan_amount>{loan_amount or '0'}</loan_amount>
            <monthly_mortgage>{monthly_mortgage or '0'}</monthly_mortgage>
            <cashflow_after_debt>{cashflow_after_debt or '0'}</cashflow_after_debt>
            <property_score>{property_score or '0'}</property_score>
            <town_score>{town_score or '0'}</town_score>
            <final_score>{final_score or '0'}</final_score>
            <grade>{xml_escape(grade) or 'unknown'}</grade>
            <decision>{xml_escape(decision) or 'unknown'}</decision>
        </property>
"""

    insert_pos = content.rfind("</properties>")
    if insert_pos != -1:
        content = content[:insert_pos] + new_property + content[insert_pos:]

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    return True

def summarize_properties():
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    property_blocks = re.findall(r"<property>(.*?)</property>", content, re.DOTALL)

    if not property_blocks:
        return "目前 memory 里还没有房产记录。"

    def extract_tag(block, tag):
        match = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
        return match.group(1).strip() if match else "unknown"

    lines = []
    for i, block in enumerate(property_blocks, start=1):
        address = extract_tag(block, "address")
        price = extract_tag(block, "price")
        size = extract_tag(block, "size")
        rent = extract_tag(block, "rent")
        location = extract_tag(block, "location")
        hoa = extract_tag(block, "hoa")
        tax = extract_tag(block, "tax")
        insurance = extract_tag(block, "insurance")
        maintenance = extract_tag(block, "maintenance")
        vacancy = extract_tag(block, "vacancy")
        ratio = extract_tag(block, "ratio")
        yield_value = extract_tag(block, "yield")
        health = extract_tag(block, "health")
        advice = extract_tag(block, "advice")
        loan_amount = extract_tag(block, "loan_amount")
        mortgage = extract_tag(block, "monthly_mortgage")
        cashflow = extract_tag(block, "cashflow_after_debt")

        lines.append(
            f"""{i}. 地址：{address}
   地点：{location}
   价格：{price}
   面积：{size}
   租金：{rent}
   HOA：{hoa}
   地税：{tax}
   保险：{insurance}
   维修：{maintenance}
   空置率：{vacancy}%
   租售比：{ratio}
   年收益率：{yield_value}
   健康程度：{health}
   建议：{advice}"""
        )

    return "这是你之前看过的房子：\n\n" + "\n\n".join(lines)

def property_exists(address):
    if not address:
        return False

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    addresses = re.findall(r"<address>(.*?)</address>", content, re.DOTALL)
    normalized_input = address.strip().lower()

    for addr in addresses:
        if addr.strip().lower() == normalized_input:
            return True

    return False

def clear_all_properties():
    ensure_memory_file()

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(
        r"<properties>.*?</properties>",
        "<properties>\n    </properties>",
        content,
        flags=re.DOTALL
    )

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    return "已清空所有房产记录。"

def load_properties():
    ensure_memory_file()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    property_blocks = re.findall(r"<property>(.*?)</property>", content, re.DOTALL)

    def extract_tag(block, tag):
        match = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
        return match.group(1).strip() if match else ""

    properties = []
    for block in property_blocks:
        prop = {
            "address": extract_tag(block, "address") or "unknown",
            "price": extract_tag(block, "price") or "0",
            "size": extract_tag(block, "size") or "unknown",
            "rent": extract_tag(block, "rent") or "0",
            "location": extract_tag(block, "location") or "unknown",
            "hoa": extract_tag(block, "hoa") or "0",
            "tax": extract_tag(block, "tax") or "0",
            "insurance": extract_tag(block, "insurance") or "0",
            "maintenance": extract_tag(block, "maintenance") or "0",
            "vacancy": extract_tag(block, "vacancy") or "0",
            "ratio": extract_tag(block, "ratio") or "0%",
            "yield": extract_tag(block, "yield") or "0%",
            "health": extract_tag(block, "health") or "unknown",
            "advice": extract_tag(block, "advice") or "unknown",
            "loan_amount": extract_tag(block, "loan_amount") or "0",
            "monthly_mortgage": extract_tag(block, "monthly_mortgage") or "0",
            "cashflow_after_debt": extract_tag(block, "cashflow_after_debt") or "0",
            "property_score": extract_tag(block, "property_score") or "0",
            "town_score": extract_tag(block, "town_score") or "0",
            "final_score": extract_tag(block, "final_score") or "0",
            "grade": extract_tag(block, "grade") or "unknown",
            "decision": extract_tag(block, "decision") or "unknown",
        }
        properties.append(prop)

    return properties

def append_memory_event(text):
    ensure_memory_file()
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)

    ensure_memory_file()

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write("""<memory>
    <user>
        <name></name>
        <language>zh</language>
    </user>
    <history>
    </history>
</memory>""")

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    new_event = f"        <event>{text}</event>\n"
    if "</history>" in content:
        content = content.replace("</history>", new_event + "    </history>")
    else:
        content = content.replace("</memory>", f"    <history>\n{new_event}    </history>\n</memory>")

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)
