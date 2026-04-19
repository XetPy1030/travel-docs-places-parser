# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

try:
    from yandex_ai_studio_sdk import AIStudio
except Exception:  # pragma: no cover - optional runtime integration
    AIStudio = None


class ImageSearcher:
    """Search images using API-first strategy with validation"""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        log_fn: Optional[Callable[..., None]] = None,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        self.serpapi_key = os.getenv("SERPAPI_API_KEY", "")
        self.google_cse_key = os.getenv("GOOGLE_CSE_API_KEY", "")
        self.google_cse_cx = os.getenv("GOOGLE_CSE_CX", "")
        self.ya_api_key = os.getenv("YA_API_KEY", "")
        self.ya_folder_id = os.getenv("YA_FOLDER_ID", "")
        self.ya_user_agent = os.getenv(
            "YA_USER_AGENT",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.112 Mobile Safari/537.36",
        )
        self.retries = 2
        self._sleep = sleep_fn or time.sleep
        self._log = log_fn or print

    def _request_json(self, url: str, params: Dict[str, Any], timeout: int = 12) -> Optional[Dict[str, Any]]:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                if response.status_code != 200:
                    self._sleep(0.5)
                    continue
                if "application/json" not in response.headers.get("Content-Type", ""):
                    self._sleep(0.5)
                    continue
                return response.json()
            except Exception:
                if attempt < self.retries:
                    self._sleep(0.5)
        return None

    def _validate_image_url(self, image_url: str, min_bytes: int = 20_000) -> bool:
        if not image_url:
            return False
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            return False
        try:
            response = self.session.get(image_url, timeout=10, stream=True)
            if response.status_code != 200:
                return False
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                return False
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) < min_bytes:
                return False
            return True
        except Exception:
            return False

    def _extract_urls_from_yandex_json(self, payload: Dict[str, Any]) -> List[str]:
        urls: List[str] = []

        def _visit(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    key_norm = key.lower()
                    if key_norm in {"url", "image_url", "img_url", "thumbnail_url", "original", "img_href"}:
                        if isinstance(value, str) and value.startswith(("http://", "https://")):
                            urls.append(value)
                    _visit(value)
            elif isinstance(node, list):
                for item in node:
                    _visit(item)

        _visit(payload)
        return urls

    def _extract_urls_from_yandex_xml(self, xml_text: str) -> List[str]:
        urls: List[str] = []
        try:
            root = ET.fromstring(xml_text)
            for elem in root.iter():
                tag = elem.tag.lower()
                if any(hint in tag for hint in ("url", "img", "image", "thumb")) and elem.text:
                    candidate = elem.text.strip()
                    if candidate.startswith(("http://", "https://")):
                        urls.append(candidate)
        except ET.ParseError:
            pass
        return urls

    def search_yandex_images(self, query: str) -> List[str]:
        """
        Search Yandex images via yandex-ai-studio-sdk.
        Requires YA_API_KEY and YA_FOLDER_ID.
        """
        if not self.ya_api_key or not self.ya_folder_id or AIStudio is None:
            return []
        try:
            sdk = AIStudio(folder_id=self.ya_folder_id, auth=self.ya_api_key)
            search = sdk.search_api.image("RU")
            search = search.configure(
                search_type="ru",
                family_mode="moderate",
                fix_typo_mode="off",
                docs_on_page=5,
                user_agent=self.ya_user_agent,
            )

            results: List[str] = []
            for page in range(2):
                raw_result = search.run(query, format="xml", page=page)
                decoded = raw_result.decode("utf-8", errors="ignore") if isinstance(raw_result, (bytes, bytearray)) else str(raw_result)
                page_urls = self._extract_urls_from_yandex_xml(decoded)
                # fallback in case API returns json-like text
                if not page_urls:
                    try:
                        payload = json.loads(decoded)
                        page_urls = self._extract_urls_from_yandex_json(payload)
                    except Exception:
                        page_urls = []
                for candidate in page_urls:
                    if candidate not in results and self._validate_image_url(candidate):
                        results.append(candidate)
                    if len(results) >= 3:
                        return results
            return results
        except Exception as error:
            self._log(f"    Yandex search error: {error}")
            return []

    def search_wikimedia(self, query: str) -> Optional[str]:
        """Search Wikimedia Commons API for image URL"""
        api_url = "https://commons.wikimedia.org/w/api.php"
        search_data = self._request_json(
            api_url,
            {
                "action": "query",
                "list": "search",
                "srsearch": f'filetype:bitmap "{query}"',
                "srlimit": 5,
                "format": "json",
            },
        )
        if not search_data:
            return None

        for item in search_data.get("query", {}).get("search", []):
            title = item.get("title", "")
            if not title:
                continue
            if not title.startswith("File:"):
                title = f"File:{title}"
            image_data = self._request_json(
                api_url,
                {
                    "action": "query",
                    "titles": title,
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "format": "json",
                },
            )
            if not image_data:
                continue
            for page in image_data.get("query", {}).get("pages", {}).values():
                imageinfo = page.get("imageinfo", [])
                if not imageinfo:
                    continue
                candidate = imageinfo[0].get("url", "")
                if self._validate_image_url(candidate):
                    return candidate
        return None

    def search_serpapi(self, query: str) -> List[str]:
        if not self.serpapi_key:
            return []
        data = self._request_json(
            "https://serpapi.com/search.json",
            {
                "engine": "google_images",
                "q": query,
                "hl": "ru",
                "api_key": self.serpapi_key,
            },
        )
        if not data:
            return []
        urls: List[str] = []
        for item in data.get("images_results", []):
            original = item.get("original", "")
            if original and self._validate_image_url(original):
                urls.append(original)
            if len(urls) >= 3:
                break
        return urls

    def search_google_cse(self, query: str) -> List[str]:
        if not self.google_cse_key or not self.google_cse_cx:
            return []
        data = self._request_json(
            "https://www.googleapis.com/customsearch/v1",
            {
                "key": self.google_cse_key,
                "cx": self.google_cse_cx,
                "q": query,
                "searchType": "image",
                "num": 5,
                "safe": "active",
            },
        )
        if not data:
            return []
        urls: List[str] = []
        for item in data.get("items", []):
            link = item.get("link", "")
            if link and self._validate_image_url(link):
                urls.append(link)
            if len(urls) >= 3:
                break
        return urls

    def find_best_photo(self, attraction_name: str, district: str, settlement: str = "") -> Tuple[str, str, float]:
        """Find best photo via API-first providers with confidence"""
        # Build search queries
        queries: List[str] = []

        # Most specific query first
        if settlement:
            queries.append(f"{attraction_name} {settlement} {district} Татарстан")

        queries.append(f"{attraction_name} {district} район Татарстан")
        queries.append(f"{attraction_name} Татарстан")

        for query in queries:
            self._log(f"    Searching: {query[:60]}...")

            # API-first #1: Wikimedia
            photo_url = self.search_wikimedia(query)
            if photo_url:
                self._log("    ✓ Found on Wikimedia")
                return photo_url, "wikimedia", 0.90

            # API-first #2: Yandex Search API via official SDK (optional)
            yandex_urls = self.search_yandex_images(query)
            if yandex_urls:
                self._log("    ✓ Found via Yandex Search API")
                return yandex_urls[0], "yandex_search_api", 0.80

            # API-first #3: SerpAPI (optional)
            serpapi_urls = self.search_serpapi(query)
            if serpapi_urls:
                self._log("    ✓ Found via SerpAPI")
                return serpapi_urls[0], "serpapi", 0.75

            # API-first #4: Google CSE (optional)
            cse_urls = self.search_google_cse(query)
            if cse_urls:
                self._log("    ✓ Found via Google CSE")
                return cse_urls[0], "google_cse", 0.70

            self._sleep(1)  # Be polite

        self._log("    ✗ No photo found")
        return "", "", 0.0
