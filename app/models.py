# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Attraction:
    """Data class for tourist attraction"""

    name: str
    district: str
    settlement: str = ""
    description_html: str = ""
    photo_url: str = ""
    photo_source: str = ""
    photo_confidence: float = 0.0
    additional_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "district": self.district,
            "settlement": self.settlement,
            "description_html": self.description_html,
            "photo_url": self.photo_url,
            "photo_source": self.photo_source,
            "photo_confidence": self.photo_confidence,
        }
        if self.additional_info:
            result["additional_info"] = self.additional_info
        return result
