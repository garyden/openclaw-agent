# utils.py

DEBUG = False

def debug(*args):
    if DEBUG:
        print("[DEBUG]", args[0] if args and isinstance(args[0], str) else "event")

def safe_float(value, default=0.0):
    try:
        text = str(value).replace("%", "").replace("$", "").replace(",", "").strip()
        if text == "":
            return default
        return float(text)
    except (ValueError, TypeError):
        return default

def parse_percent(value):
    if not value:
        return 0.0
    value = value.replace("%", "").strip()
    try:
        return float(value)
    except ValueError:
        return 0.0

def parse_city_state(location: str):
    if not location:
        return "", ""

    parts = [p.strip() for p in location.split(",")]
    if len(parts) >= 2:
        return parts[0], parts[1].split()[0].upper()

    return location.strip(), ""

def xml_escape(text):
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
