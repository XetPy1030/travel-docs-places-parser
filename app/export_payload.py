# -*- coding: utf-8 -*-
"""Сборка структуры экспорта без записи на диск (удобно для тестов)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.models import Attraction


def build_quality_stats(
    quality_stats: Dict[str, int],
    total: int,
    processed_files_count: int,
    success_files_count: int,
    errors_count: int,
) -> Dict[str, Any]:
    return {
        "attractions_with_photo_percent": round((quality_stats["with_photo"] / total * 100), 2) if total else 0,
        "descriptions_with_min_paragraphs_percent": round(
            (quality_stats["with_min_paragraphs"] / total * 100), 2
        )
        if total
        else 0,
        "high_confidence_percent": round((quality_stats["high_confidence"] / total * 100), 2) if total else 0,
        "processed_files": processed_files_count,
        "successful_files": success_files_count,
        "file_success_percent": round((success_files_count / processed_files_count * 100), 2)
        if processed_files_count
        else 0,
        "errors_count": errors_count,
    }


def build_export_payload(
    attractions: List[Attraction],
    *,
    quality_stats: Dict[str, int],
    processed_files_count: int,
    success_files_count: int,
    errors_count: int,
    ai_model: str,
    ai_requests: int,
    estimated_tokens: int,
    cache_version: str,
    prompt_version: str,
    processed_at: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Вернуть (полный документ для JSON, блок quality)."""
    districts: Dict[str, List[Dict[str, Any]]] = {}
    for attr in attractions:
        if attr.district not in districts:
            districts[attr.district] = []
        districts[attr.district].append(attr.to_dict())

    total = len(attractions)
    quality = build_quality_stats(
        quality_stats,
        total,
        processed_files_count,
        success_files_count,
        errors_count,
    )

    ts = processed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data: Dict[str, Any] = {
        "metadata": {
            "total_attractions": len(attractions),
            "total_districts": len(districts),
            "processed_at": ts,
            "ai_model": ai_model,
            "ai_requests": ai_requests,
            "estimated_tokens": estimated_tokens,
            "cache_version": cache_version,
            "prompt_version": prompt_version,
            "districts": list(districts.keys()),
        },
        "quality": quality,
        "attractions": [attr.to_dict() for attr in attractions],
        "by_district": districts,
    }
    return data, quality
