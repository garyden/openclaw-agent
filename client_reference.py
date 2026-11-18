from __future__ import annotations

import re
from difflib import SequenceMatcher


def _normalize_name(value: object) -> str:
    text = str(value or "").casefold().strip()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


def resolve_client_reference(
    spoken_name: str,
    clients: list[dict],
    *,
    likely_threshold: float = 0.78,
    ambiguity_margin: float = 0.08,
) -> dict:
    """Resolve a spoken name without silently guessing between close candidates."""
    target = _normalize_name(spoken_name)
    named_clients = [
        client for client in clients if _normalize_name(client.get("name", ""))
    ]
    if not target:
        return {"status": "not_found", "client": None, "candidates": [], "score": 0.0}

    exact = [
        client
        for client in named_clients
        if _normalize_name(client.get("name", "")) == target
    ]
    if len(exact) == 1:
        return {"status": "exact", "client": exact[0], "candidates": exact, "score": 1.0}
    if len(exact) > 1:
        return {"status": "ambiguous", "client": None, "candidates": exact, "score": 1.0}

    scored = sorted(
        (
            (
                SequenceMatcher(
                    None,
                    target,
                    _normalize_name(client.get("name", "")),
                ).ratio(),
                client,
            )
            for client in named_clients
        ),
        key=lambda item: (-item[0], str(item[1].get("name", "")).casefold()),
    )
    if not scored or scored[0][0] < likely_threshold:
        return {"status": "not_found", "client": None, "candidates": [], "score": 0.0}

    top_score = scored[0][0]
    close = [
        client
        for score, client in scored
        if score >= likely_threshold and top_score - score < ambiguity_margin
    ]
    if len(close) > 1:
        return {
            "status": "ambiguous",
            "client": None,
            "candidates": close[:3],
            "score": top_score,
        }

    return {
        "status": "likely",
        "client": scored[0][1],
        "candidates": [scored[0][1]],
        "score": top_score,
    }
