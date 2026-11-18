from utils import parse_city_state
from town_analyzer import format_town_report
from scoring import format_final_investment_report


def build_property_town_report(info, analysis_text, town_result, final_result):
    city, state = parse_city_state(info.get("location", ""))

    sections = [analysis_text]

    if city and state:
        town_report = format_town_report(city, state, town_result)
        sections.append(town_report)
    else:
        sections.append("Town 分析：无法识别城市和州。")

    final_report = format_final_investment_report(final_result)
    sections.append(final_report)

    return "\n\n".join(sections)
