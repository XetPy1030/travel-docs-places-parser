# -*- coding: utf-8 -*-
"""Чистые функции валидации и нормализации для удобного unit-тестирования."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


def count_html_paragraphs(html: str) -> int:
    return len(re.findall(r"<p>.*?</p>", html, flags=re.DOTALL))


def has_language_artifacts(html: str) -> bool:
    latin_words = re.findall(r"\b[A-Za-z]{4,}\b", html)
    return len(latin_words) > 0


def is_list_like_text(text: str) -> bool:
    """Грубая эвристика: текст похож на список пунктов, а не на цельное описание."""
    if not text:
        return False
    normalized = text.replace("</p><p>", "\n").replace("<p>", "").replace("</p>", "")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    numbered = 0
    bullets = 0
    for line in lines:
        if re.match(r"^\d+[.)-]\s+", line):
            numbered += 1
        if re.match(r"^[-*•]\s+", line):
            bullets += 1
    return (numbered + bullets) >= 2


def normalize_settlement_pair(
    district: str,
    raw_settlement: str,
    settlement_map: Dict[str, List[str]],
) -> Tuple[str, str]:
    """Сопоставить населённый пункт со справочником района; вернуть (канон, raw)."""
    if not raw_settlement:
        return "", ""
    settlements = settlement_map.get(district, [])
    raw_norm = raw_settlement.lower().strip()
    for known in settlements:
        if known.lower() == raw_norm:
            return known, raw_settlement
        if known.lower() in raw_norm or raw_norm in known.lower():
            return known, raw_settlement
    return raw_settlement, raw_settlement


def validate_extracted_attraction(attr_data: Dict) -> Optional[Dict]:
    name = str(attr_data.get("name", "")).strip()
    if len(name) < 3:
        return None
    settlement = str(attr_data.get("settlement", "")).strip()
    brief = str(attr_data.get("brief_description", "")).strip()
    attr_type = str(attr_data.get("type", "")).strip() or "не определено"
    source_fragment = str(attr_data.get("source_fragment", "")).strip()[:200]
    confidence_raw = attr_data.get("confidence", 0.5)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    return {
        "name": name,
        "settlement": settlement,
        "brief_description": brief,
        "type": attr_type,
        "confidence": confidence,
        "source_fragment": source_fragment,
    }
