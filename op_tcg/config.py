"""Stałe: API, pliki, regex."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

OPTCG_API_BASE = "https://api.egmanevents.com/api/cards"
NAKAMADECKS_API = "https://nav-api.nakamadecks.com/cards"
OPTCGAPI_ALL_SET_CARDS = "https://optcgapi.com/api/allSetCards/"
OPTCGAPI_ALL_ST_CARDS = "https://optcgapi.com/api/allSTCards/"
OPTCGAPI_ALL_PROMO_CARDS = "https://optcgapi.com/api/allPromoCards/"

CACHE_FILE = Path("op_tcg_cards_cache.json")
USER_DECKS_FILE = Path("op_tcg_user_decks.json")
OWNED_FILE = Path("op_tcg_data.json")

FILTER_ALL = "Wszystkie"
THUMB_WORKERS = 3
CARD_ID_RE = re.compile(r"\bOP\d{2}-\d{3}[A-Za-z0-9_-]*\b")


@dataclass(frozen=True)
class CardSource:
    name: str
    url: str
    parse: Callable[[Any], list[dict[str, Any]]]


def _as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "cards", "results"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    return []


def parse_generic_cards(payload: Any) -> list[dict[str, Any]]:
    return [c for c in _as_list(payload) if isinstance(c, dict)]


def parse_optcgapi_cards(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    return parse_generic_cards(payload)


CARD_SOURCES: list[CardSource] = [
    CardSource(name="OPTCG API", url=OPTCG_API_BASE, parse=parse_generic_cards),
    CardSource(name="NakamaDecks API", url=NAKAMADECKS_API, parse=parse_generic_cards),
    CardSource(name="OPTCGAPI (all set cards)", url=OPTCGAPI_ALL_SET_CARDS, parse=parse_optcgapi_cards),
    CardSource(name="OPTCGAPI (all starter deck cards)", url=OPTCGAPI_ALL_ST_CARDS, parse=parse_optcgapi_cards),
    CardSource(name="OPTCGAPI (all promo cards)", url=OPTCGAPI_ALL_PROMO_CARDS, parse=parse_optcgapi_cards),
]
