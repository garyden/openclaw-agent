from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from typing import Any, Dict, List, Optional


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XML_PATH = os.path.join(BASE_DIR, "memory", "memory.xml")

VALID_STATUSES = {
    "new_lead",
    "active",
    "touring",
    "offer_submitted",
    "closed",
    "paused",
}


# Exact aliases only: mixed, negated, or uncertain statuses must be clarified.
STATUS_ALIASES = {
    '新线索': 'new_lead', '新線索': 'new_lead', '新客户': 'new_lead', '新客戶': 'new_lead',
    'lead': 'new_lead',
    '活跃': 'active', '活躍': 'active', '跟进中': 'active', '跟進中': 'active',
    '正在跟进': 'active', '正在跟進': 'active', 'actively following up': 'active',
    '看房中': 'touring', '看房': 'touring', '正在看房': 'touring',
    '带看中': 'touring', '帶看中': 'touring', 'viewing': 'touring', 'viewing homes': 'touring',
    '已报价': 'offer_submitted', '已報價': 'offer_submitted',
    '已出价': 'offer_submitted', '已出價': 'offer_submitted',
    '已提交报价': 'offer_submitted', '已提交報價': 'offer_submitted',
    'submitted offer': 'offer_submitted',
    '已成交': 'closed', '成交': 'closed', 'deal closed': 'closed',
    '暂停': 'paused', '暫停': 'paused', '已暂停': 'paused', '已暫停': 'paused',
    '暂缓': 'paused', '暫緩': 'paused', 'on hold': 'paused',
}


def normalize_client_status(status: Any) -> Optional[str]:
    """Return a canonical status or None; never infer intent from substrings."""
    if not isinstance(status, str):
        return None
    key = ' '.join(re.sub(r'[_-]+', ' ', status.casefold()).split())
    canonical = key.replace(' ', '_')
    if canonical in VALID_STATUSES:
        return canonical
    return STATUS_ALIASES.get(key)


CLIENT_FIELDS = [
    "name",
    "email",
    "phone",
    "address",
    "budget",
    "areas",
    "requirements",
    "status",
    "notes",
    "birthday",
    "last_contact",
    "next_followup",
]

DEFAULT_CLIENT = {
    "name": "",
    "email": "",
    "phone": "",
    "address": "",
    "budget": "",
    "areas": "",
    "requirements": "",
    "status": "new_lead",
    "notes": "",
    "birthday": "",
    "last_contact": "",
    "next_followup": "",
}

FIELD_ALIASES = {
    "name": "name",
    "client": "name",
    "client_name": "name",

    "email": "email",
    "mail": "email",

    "phone": "phone",
    "mobile": "phone",
    "tel": "phone",

    "address": "address",

    "budget": "budget",
    "price_range": "budget",
    "max_budget": "budget",

    "areas": "areas",
    "area": "areas",
    "locations": "areas",
    "location": "areas",
    "towns": "areas",

    "requirements": "requirements",
    "requirement": "requirements",
    "needs": "requirements",
    "criteria": "requirements",

    "status": "status",
    "stage": "status",

    "notes": "notes",
    "note": "notes",
    "comments": "notes",

    "birthday": "birthday",
    "birthdate": "birthday",

    "last_contact": "last_contact",
    "lastcontact": "last_contact",

    "next_followup": "next_followup",
    "nextfollowup": "next_followup",
    "followup": "next_followup",
    "next_follow_up": "next_followup",
}


class ClientManager:
    """
    Simple XML-based CRM manager for MVP use.

    Features:
    - CRUD client storage
    - XML persistence
    - simple validation
    - easy text parsing for Telegram-style input
    """

    def __init__(self, xml_path: str = DEFAULT_XML_PATH) -> None:
        self.xml_path = xml_path
        self._ensure_memory_file()

    # ============================================================
    # Public structured API
    # ============================================================

    def add_client(
        self,
        name: str,
        email: str = "",
        phone: str = "",
        address: str = "",
        budget: str = "",
        areas: str = "",
        requirements: str = "",
        status: str = "new_lead",
        notes: str = "",
        birthday: str = "",
        last_contact: str = "",
        next_followup: str = "",
    ) -> Dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Client name is required.")

        status = self._normalize_status(status)

        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)

        if self._find_client_element(clients_node, name) is not None:
            raise ValueError(f"Client '{name}' already exists.")

        client_data = {
            "name": name,
            "email": email.strip(),
            "phone": phone.strip(),
            "address": address.strip(),
            "budget": budget.strip(),
            "areas": areas.strip(),
            "requirements": requirements.strip(),
            "status": status,
            "notes": notes.strip(),
            "birthday": birthday.strip(),
            "last_contact": last_contact.strip(),
            "next_followup": next_followup.strip(),
        }

        client_el = ET.SubElement(clients_node, "client")
        self._write_client_fields(client_el, client_data)
        self._save_root(root)

        return client_data

    def get_client(self, name: str) -> Optional[Dict[str, Any]]:
        name = name.strip()
        if not name:
            return None

        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)
        client_el = self._find_unique_client_element(clients_node, name)

        if client_el is None:
            return None

        return self._element_to_client_dict(client_el)

    def suggest_client_name(self, name: str) -> Optional[str]:
        target = self._normalize_name(name)
        if not target:
            return None

        clients = self.list_clients()
        normalized_to_display = {
            self._normalize_name(client.get("name", "")): client.get("name", "").strip()
            for client in clients
            if client.get("name", "").strip()
        }

        matches = get_close_matches(
            target,
            list(normalized_to_display.keys()),
            n=1,
            cutoff=0.8,
        )
        if not matches:
            return None

        return normalized_to_display[matches[0]]

    def list_clients(self) -> List[Dict[str, Any]]:
        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)

        clients = [
            self._element_to_client_dict(client_el)
            for client_el in clients_node.findall("client")
        ]

        return sorted(clients, key=lambda x: x.get("name", "").lower())

    def update_client(self, name: str, **fields: Any) -> Dict[str, Any]:
        target_name = name.strip()
        if not target_name:
            raise ValueError("Client name is required.")

        if not fields:
            raise ValueError("No update fields provided.")

        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)
        client_el = self._find_unique_client_element(clients_node, target_name)

        if client_el is None:
            raise ValueError(f"Client '{target_name}' not found.")

        normalized_fields = self._normalize_input_fields(fields)

        for key in normalized_fields:
            if key not in CLIENT_FIELDS:
                raise ValueError(f"Invalid client field: '{key}'")

        new_name = str(normalized_fields.get("name", target_name)).strip()
        if not new_name:
            raise ValueError("Client name cannot be empty.")

        if self._normalize_name(new_name) != self._normalize_name(target_name):
            existing = self._find_client_element(clients_node, new_name)
            if existing is not None:
                raise ValueError(f"Client '{new_name}' already exists.")

        if "status" in normalized_fields:
            normalized_fields["status"] = self._normalize_status(str(normalized_fields["status"]))

        current_data = self._element_to_client_dict(client_el)

        for key, value in normalized_fields.items():
            current_data[key] = "" if value is None else str(value).strip()

        self._write_client_fields(client_el, current_data)
        self._save_root(root)

        return current_data

    def delete_client(self, name: str) -> bool:
        target_name = name.strip()
        if not target_name:
            return False

        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)
        client_el = self._find_unique_client_element(clients_node, target_name)

        if client_el is None:
            return False

        clients_node.remove(client_el)
        self._save_root(root)
        return True

    def add_clients_batch(self, clients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate all clients, then persist the complete batch in one atomic save."""
        root = self._load_root()
        clients_node = self._get_or_create_clients_node(root)
        prepared = []
        batch_names = set()

        for raw_client in clients:
            data = DEFAULT_CLIENT.copy()
            data.update(self._normalize_input_fields(raw_client))
            data["name"] = data["name"].strip()
            if not data["name"]:
                raise ValueError("Client name is required.")
            data["status"] = self._normalize_status(data["status"] or "new_lead")

            name_key = self._normalize_name(data["name"])
            if name_key in batch_names or self._find_client_element(clients_node, data["name"]) is not None:
                raise ValueError(f"Client '{data['name']}' already exists.")
            batch_names.add(name_key)
            prepared.append(data)

        for data in prepared:
            client_el = ET.SubElement(clients_node, "client")
            self._write_client_fields(client_el, data)

        if prepared:
            self._save_root(root)
        return prepared

    def format_client_report(self, client: Dict[str, Any], lang: str = "en") -> str:
        if not client:
            return "Client not found."

        if (lang or "en").lower() == "zh":
            return self._format_client_report_zh(client)

        return self._format_client_report_en(client)

    # ============================================================
    # Easy input API
    # ============================================================

    def parse_client_text(self, text: str) -> Dict[str, str]:
        """
        Parse easy client input text into a clean field dict.

        Supported formats:

        1) Multi-line:
            name: John Smith
            phone: 1234567890
            email: john@example.com

        2) One-line:
            name=John Smith; phone=1234567890; email=john@example.com
        """
        if not text or not text.strip():
            raise ValueError("Input text is empty.")

        raw = text.strip()

        if "\n" in raw:
            pairs = self._parse_multiline_pairs(raw)
        else:
            pairs = self._parse_singleline_pairs(raw)

        if not pairs:
            raise ValueError("Could not parse any valid client fields.")

        normalized = self._normalize_input_fields(pairs)

        if "status" in normalized and normalized["status"]:
            normalized["status"] = self._normalize_status(normalized["status"])

        return normalized

    def add_client_from_text(self, text: str) -> Dict[str, Any]:
        parsed = self.parse_client_text(text)

        name = parsed.get("name", "").strip()
        if not name:
            raise ValueError("Client name is required. Please include 'name:' or 'name='.")

        client_data = DEFAULT_CLIENT.copy()
        client_data.update(parsed)

        return self.add_client(
            name=client_data["name"],
            email=client_data["email"],
            phone=client_data["phone"],
            address=client_data["address"],
            budget=client_data["budget"],
            areas=client_data["areas"],
            requirements=client_data["requirements"],
            status=client_data["status"],
            notes=client_data["notes"],
            birthday=client_data["birthday"],
            last_contact=client_data["last_contact"],
            next_followup=client_data["next_followup"],
        )

    def update_client_from_text(self, name: str, text: str) -> Dict[str, Any]:
        parsed = self.parse_client_text(text)

        if not parsed:
            raise ValueError("No valid fields found to update.")

        return self.update_client(name, **parsed)

    # ============================================================
    # Internal helpers
    # ============================================================

    def _ensure_memory_file(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.xml_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        if not os.path.exists(self.xml_path):
            root = ET.Element("memory")
            ET.SubElement(root, "properties")
            ET.SubElement(root, "towns")
            ET.SubElement(root, "clients")
            self._save_tree(ET.ElementTree(root))
            return

        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()

            if root.tag != "memory":
                raise ValueError("Root tag must be <memory>")

            changed = False
            for section in ("properties", "towns", "clients"):
                if root.find(section) is None:
                    ET.SubElement(root, section)
                    changed = True

            if changed:
                self._save_tree(tree)

        except ET.ParseError as exc:
            raise ValueError(f"Invalid XML file: {self.xml_path}") from exc

    def _load_root(self) -> ET.Element:
        tree = ET.parse(self.xml_path)
        return tree.getroot()

    def _save_root(self, root: ET.Element) -> None:
        tree = ET.ElementTree(root)
        self._save_tree(tree)

    def _save_tree(self, tree: ET.ElementTree) -> None:
        self._indent_xml(tree.getroot())
        directory = os.path.dirname(os.path.abspath(self.xml_path)) or "."
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=directory) as temp_file:
            temp_path = temp_file.name
            tree.write(temp_file, encoding="utf-8", xml_declaration=True)
            temp_file.write(b"\n")

        os.replace(temp_path, self.xml_path)

    def _get_or_create_clients_node(self, root: ET.Element) -> ET.Element:
        clients_node = root.find("clients")
        if clients_node is None:
            clients_node = ET.SubElement(root, "clients")
        return clients_node

    def _find_client_element(self, clients_node: ET.Element, name: str) -> Optional[ET.Element]:
        target = self._normalize_name(name)
        for client_el in clients_node.findall("client"):
            name_el = client_el.find("name")
            if name_el is not None and self._normalize_name(name_el.text or "") == target:
                return client_el
        return None

    def _find_unique_client_element(self, clients_node: ET.Element, name: str) -> Optional[ET.Element]:
        exact = self._find_client_element(clients_node, name)
        if exact is not None:
            return exact

        target = self._normalize_name(name)
        if not target:
            return None

        matches = []
        for client_el in clients_node.findall("client"):
            name_el = client_el.find("name")
            candidate = self._normalize_name(name_el.text or "") if name_el is not None else ""
            if candidate.startswith(target + " "):
                matches.append(client_el)

        if len(matches) == 1:
            return matches[0]

        return None

    def _normalize_name(self, name: str) -> str:
        return " ".join((name or "").strip().lower().split())

    def _element_to_client_dict(self, client_el: ET.Element) -> Dict[str, Any]:
        data = DEFAULT_CLIENT.copy()
        for field in CLIENT_FIELDS:
            field_el = client_el.find(field)
            data[field] = (field_el.text or "").strip() if field_el is not None else data[field]

        data["status"] = data["status"] or "new_lead"
        return data

    def _write_client_fields(self, client_el: ET.Element, data: Dict[str, Any]) -> None:
        for field in CLIENT_FIELDS:
            field_el = client_el.find(field)
            if field_el is None:
                field_el = ET.SubElement(client_el, field)

            value = data.get(field, DEFAULT_CLIENT[field])
            field_el.text = "" if value is None else str(value).strip()

    def _normalize_status(self, status: str) -> str:
        normalized = normalize_client_status(status)
        if normalized not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Valid statuses: {', '.join(sorted(VALID_STATUSES))}"
            )
        return normalized

    def _normalize_input_fields(self, fields: Dict[str, Any]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}

        for raw_key, raw_value in fields.items():
            key = self._canonical_field_name(str(raw_key))
            if not key:
                continue

            value = "" if raw_value is None else str(raw_value).strip()
            normalized[key] = value

        return normalized

    def _canonical_field_name(self, key: str) -> Optional[str]:
        clean_key = key.strip().lower()
        clean_key = clean_key.replace(" ", "_")
        clean_key = clean_key.replace("-", "_")

        return FIELD_ALIASES.get(clean_key)

    def _parse_multiline_pairs(self, text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            if ":" in line:
                key, value = line.split(":", 1)
            elif "=" in line:
                key, value = line.split("=", 1)
            else:
                continue

            key = key.strip()
            value = value.strip()

            if key:
                result[key] = value

        return result

    def _parse_singleline_pairs(self, text: str) -> Dict[str, str]:
        """
        Parse one-line format like:
        name=John Smith; phone=123; email=a@b.com

        Also accepts commas as separators when fields are clearly key=value or key:value.
        """
        result: Dict[str, str] = {}

        parts = re.split(r"[;\n|]+", text)
        if len(parts) == 1:
            parts = re.split(r",(?=\s*[A-Za-z_][A-Za-z0-9_\- ]*\s*[:=])", text)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if ":" in part:
                key, value = part.split(":", 1)
            elif "=" in part:
                key, value = part.split("=", 1)
            else:
                continue

            key = key.strip()
            value = value.strip()

            if key:
                result[key] = value

        return result

    def _format_client_report_en(self, client: Dict[str, Any]) -> str:
        lines = [
            f"Client: {client.get('name', '')}",
            f"Status: {client.get('status', '')}",
            f"Email: {client.get('email', '') or '-'}",
            f"Phone: {client.get('phone', '') or '-'}",
            f"Address: {client.get('address', '') or '-'}",
            f"Budget: {client.get('budget', '') or '-'}",
            f"Areas: {client.get('areas', '') or '-'}",
            f"Requirements: {client.get('requirements', '') or '-'}",
            f"Birthday: {client.get('birthday', '') or '-'}",
            f"Last Contact: {client.get('last_contact', '') or '-'}",
            f"Next Follow-up: {client.get('next_followup', '') or '-'}",
            f"Notes: {client.get('notes', '') or '-'}",
        ]
        return "\n".join(lines)

    def _format_client_report_zh(self, client: Dict[str, Any]) -> str:
        status_map = {
            "new_lead": "新线索",
            "active": "活跃跟进",
            "touring": "带看中",
            "offer_submitted": "已提交报价",
            "closed": "已成交",
            "paused": "暂停",
        }

        lines = [
            f"客户: {client.get('name', '')}",
            f"状态: {status_map.get(client.get('status', ''), client.get('status', ''))}",
            f"邮箱: {client.get('email', '') or '-'}",
            f"电话: {client.get('phone', '') or '-'}",
            f"地址: {client.get('address', '') or '-'}",
            f"预算: {client.get('budget', '') or '-'}",
            f"区域: {client.get('areas', '') or '-'}",
            f"需求: {client.get('requirements', '') or '-'}",
            f"生日: {client.get('birthday', '') or '-'}",
            f"上次联系: {client.get('last_contact', '') or '-'}",
            f"下次跟进: {client.get('next_followup', '') or '-'}",
            f"备注: {client.get('notes', '') or '-'}",
        ]
        return "\n".join(lines)

    def _indent_xml(self, elem: ET.Element, level: int = 0) -> None:
        indent = "\n" + ("    " * level)
        child_indent = "\n" + ("    " * (level + 1))

        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = child_indent
            for child in elem:
                self._indent_xml(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent
