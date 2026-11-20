import re
import xml.etree.ElementTree as ET

from app_config import read_app_env, resolve_memory_path
from client_manager import ClientManager
from crm_storage import write_memory
from utils import xml_escape


def _load_memory():
    production = read_app_env() == 'production'
    path = resolve_memory_path()
    if not production and not path.exists():
        ClientManager(path)

    content = path.read_text(encoding='utf-8')
    root = ET.fromstring(content, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != 'memory':
        raise ValueError("Root tag must be <memory>")

    # Legacy commands expect explicit opening and closing tags for these sections.
    # Prepare them in memory, so reads do not migrate or rewrite an existing file.
    if any(f'<{tag}>' not in content for tag in ('facts', 'preferences', 'history', 'properties')):
        if root.find('user') is None:
            user = ET.SubElement(root, 'user')
            ET.SubElement(user, 'name')
            ET.SubElement(user, 'language').text = 'zh'
        for tag in ('facts', 'preferences', 'history', 'properties'):
            if root.find(tag) is None:
                ET.SubElement(root, tag)
        content = ET.tostring(root, encoding='unicode', short_empty_elements=False)
    return path, production, content


def _save_memory(path, production, content):
    ET.fromstring(content)
    write_memory(path, content.encode('utf-8'), production=production)


def ensure_memory_file():
    _load_memory()


def load_memory():
    return _load_memory()[2]


def append_fact(text):
    path, production, content = _load_memory()
    new_fact = f"        <fact>{xml_escape(text)}</fact>\n"
    content = content.replace("</facts>", new_fact + "    </facts>", 1)
    _save_memory(path, production, content)


def delete_property(address):
    if not address or not address.strip():
        return False, "没有提供房产地址。"

    path, production, content = _load_memory()

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

    _save_memory(path, production, content)

    return True, f"已删除房产：{matched_address}"

def append_preference(text):
    path, production, content = _load_memory()

    new_pref = f"        <preference>{xml_escape(text)}</preference>\n"
    if "</preferences>" in content:
        content = content.replace("</preferences>", new_pref + "    </preferences>")

    _save_memory(path, production, content)

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
    address_key = " ".join((address or "").lower().strip().split())
    path, production, content = _load_memory()
    if _property_exists(content, address_key):
        return False

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

    _save_memory(path, production, content)

    return True

def summarize_properties():
    content = load_memory()

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
    return bool(address) and _property_exists(load_memory(), address)


def _property_exists(content, address):
    addresses = re.findall(r"<address>(.*?)</address>", content, re.DOTALL)
    normalized_input = address.strip().lower()

    for addr in addresses:
        if addr.strip().lower() == normalized_input:
            return True

    return False

def clear_all_properties():
    path, production, content = _load_memory()

    content = re.sub(
        r"<properties>.*?</properties>",
        "<properties>\n    </properties>",
        content,
        flags=re.DOTALL
    )

    _save_memory(path, production, content)

    return "已清空所有房产记录。"

def load_properties():
    content = load_memory()

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
    path, production, content = _load_memory()
    new_event = f"        <event>{xml_escape(text)}</event>\n"
    content = content.replace("</history>", new_event + "    </history>", 1)
    _save_memory(path, production, content)
