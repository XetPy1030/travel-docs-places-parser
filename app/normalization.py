# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class DistrictNormalizer:
    """Normalize district names using provided mapping"""

    def __init__(self, districts_json: Optional[str] = None):
        self.district_map: Dict[str, str] = {}  # normalized_name -> official_name
        self.settlement_map: Dict[str, List[str]] = {}  # district_name -> [settlements]

        if districts_json:
            self.load_from_json(districts_json)

    def load_from_json(self, json_data: Any) -> None:
        """Load districts and settlements from JSON"""
        if isinstance(json_data, str):
            try:
                data = json.loads(json_data)
            except Exception:
                data = []
        else:
            data = json_data

        districts: Dict[int, str] = {}
        settlements: Dict[str, List[str]] = {}

        for item in data:
            if item.get("model") == "locations.District":
                districts[item["pk"]] = item["fields"]["name"]
            elif item.get("model") == "locations.Settlement":
                dist_id = item["fields"].get("district")
                settlement_name = item["fields"]["name"]
                if dist_id and dist_id in districts:
                    dist_name = districts[dist_id]
                    if dist_name not in settlements:
                        settlements[dist_name] = []
                    settlements[dist_name].append(settlement_name)

        # Create normalization map
        for dist_name in districts.values():
            normalized = self._normalize_name(dist_name)
            self.district_map[normalized] = dist_name

        self.settlement_map = settlements

    def _normalize_name(self, name: str) -> str:
        """Normalize district name for matching"""
        name = name.lower().strip()
        # Remove common suffixes
        for suffix in [" район", "district", "р-н"]:
            name = name.replace(suffix, "")
        return name.strip()

    def normalize(self, folder_name: str) -> str:
        """Normalize folder name to official district name"""
        normalized = self._normalize_name(folder_name)

        # Try exact match
        if normalized in self.district_map:
            return self.district_map[normalized]

        # Try partial match
        for key, value in self.district_map.items():
            if key in normalized or normalized in key:
                return value

        # Return cleaned folder name
        return folder_name.replace(" район", "").strip() + "ский район"

    def find_settlement(self, district: str, text: str) -> str:
        """Find settlement name in text for given district"""
        settlements = self.settlement_map.get(district, [])

        for settlement in settlements:
            if settlement.lower() in text.lower():
                return settlement

        return ""
