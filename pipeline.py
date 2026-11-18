# pipeline.py

from town_data_manager import ensure_town_data
from town_analyzer import analyze_town
from scoring import score_town
from town_analyzer import format_town_report


def run_town_pipeline(city: str, state: str) -> dict:
    if not ensure_town_data(city, state):
        return {
            "success": False,
            "city": city,
            "state": state,
            "analysis": None,
            "score": None,
            "report": "",
            "message": f"No market data found for {city}, {state}",
        }

    analysis = analyze_town(city, state)
    if not analysis:
        return {
            "success": False,
            "city": city,
            "state": state,
            "analysis": None,
            "score": None,
            "report": "",
            "message": f"Town analysis failed for {city}, {state}",
        }

    score = score_town(analysis)
    report = format_town_report(city, state, analysis, score)

    return {
        "success": True,
        "city": city,
        "state": state,
        "analysis": analysis,
        "score": score,
        "report": report,
        "message": "",
    }
