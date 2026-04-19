# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.docx_parser import DOCXParser
from app.export_payload import build_export_payload
from app.image_search import ImageSearcher
from app.models import Attraction
from app.normalization import DistrictNormalizer
from app.openrouter import OpenRouterClient
from app import validation


class AttractionProcessor:
    """Main processor for attractions"""

    CACHE_VERSION = "2.0"
    CONFIDENCE_THRESHOLD = 0.7

    def __init__(
        self,
        openrouter_api_key: str,
        districts_json: Optional[str] = None,
        model: str = "meta-llama/llama-3.1-70b-instruct",
        skip_photos: bool = False,
        min_description_paragraphs: int = 2,
        retry_count: int = 2,
        resume: bool = False,
        max_files: int = 0,
        only_district: str = "",
        output_dir: str = "output",
        *,
        docx_parser: Optional[DOCXParser] = None,
        ai_client: Optional[OpenRouterClient] = None,
        image_searcher: Optional[ImageSearcher] = None,
        normalizer: Optional[DistrictNormalizer] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        log_fn: Optional[Callable[..., None]] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.parser = docx_parser or DOCXParser()
        self.ai_client = ai_client or OpenRouterClient(
            openrouter_api_key,
            model=model,
            max_retries=2,
            error_hook=self._on_ai_error,
            log_fn=log_fn,
        )
        self.image_searcher = image_searcher or ImageSearcher()
        self.normalizer = normalizer if normalizer is not None else DistrictNormalizer(districts_json)
        self._sleep = sleep_fn or time.sleep
        self._log = log_fn or print
        self.processed_count = 0
        self.processed_files_count = 0
        self.success_files_count = 0
        self.cache_file = str(self.output_dir / "processing_cache.json")
        self.state_file = str(self.output_dir / "processing_state.json")
        self.error_file = str(self.output_dir / "processing_errors.json")
        self.skip_photos = skip_photos
        self.min_description_paragraphs = min_description_paragraphs
        self.retry_count = retry_count
        self.max_files = max_files
        self.only_district = only_district.lower().strip()
        self.resume = resume
        self.errors: List[Dict[str, Any]] = []
        self.quality_stats = {
            "with_photo": 0,
            "with_min_paragraphs": 0,
            "high_confidence": 0,
            "low_confidence": 0,
            "list_like_descriptions": 0,
            "rejected_descriptions": 0,
            "ai_errors": 0,
        }
        self.config_signature = hashlib.md5(
            json.dumps(
                {
                    "model": model,
                    "prompt_version": self.ai_client.prompt_version,
                    "min_description_paragraphs": min_description_paragraphs,
                    "skip_photos": skip_photos,
                    "retry_count": retry_count,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.cache = self._load_cache()
        self.state = self._load_state()

    def _load_cache(self) -> Dict[str, Any]:
        """Load processing cache"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("_meta"):
                    return data
                return {"_meta": {}, "items": data if isinstance(data, dict) else {}}
        except Exception:
            pass
        return {"_meta": {}, "items": {}}

    def _save_cache(self) -> None:
        """Save processing cache"""
        self.cache["_meta"] = {
            "version": self.CACHE_VERSION,
            "config_signature": self.config_signature,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_state(self) -> Dict[str, Any]:
        if not self.resume or not os.path.exists(self.state_file):
            return {"processed_files": []}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "processed_files" in data:
                    return data
        except Exception:
            pass
        return {"processed_files": []}

    def _save_state(self) -> None:
        data = {
            "processed_files": self.state.get("processed_files", []),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_errors(self) -> None:
        try:
            with open(self.error_file, "w", encoding="utf-8") as f:
                json.dump(self.errors, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _log_error(self, file_path: str, error_type: str, message: str) -> None:
        self.errors.append(
            {
                "file": file_path,
                "error_type": error_type,
                "message": message,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def _on_ai_error(self, message: str) -> None:
        self.quality_stats["ai_errors"] += 1
        self._log_error("openrouter", "ai_connection_error", message)

    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file content"""
        try:
            with open(file_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""

    def _count_html_paragraphs(self, html: str) -> int:
        return validation.count_html_paragraphs(html)

    def _has_language_artifacts(self, html: str) -> bool:
        return validation.has_language_artifacts(html)

    def _normalize_settlement(self, district: str, settlement: str) -> tuple[str, str]:
        return validation.normalize_settlement_pair(
            district,
            settlement or "",
            self.normalizer.settlement_map,
        )

    def _validate_extracted_attraction(self, attr_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return validation.validate_extracted_attraction(attr_data)

    def _expand_list_like_attractions(
        self,
        attractions_data: List[Dict[str, Any]],
        source_text: str,
    ) -> List[Dict[str, Any]]:
        """
        If LLM returned one list-like object, split it into multiple attractions.
        """
        expanded: List[Dict[str, Any]] = []
        for item in attractions_data:
            name = item.get("name", "")
            brief = item.get("brief_description", "")
            source_fragment = item.get("source_fragment", "")
            blob = "\n".join([name, brief, source_fragment, source_text[:1200]])
            list_lines = []
            for line in blob.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"^\d+[.)]?\s*(.+)$", line)
                if match:
                    list_lines.append(match.group(1).strip())

            if len(list_lines) >= 3:
                try:
                    base_confidence = float(item.get("confidence", 0.5))
                except (TypeError, ValueError):
                    base_confidence = 0.5
                for line in list_lines[:30]:
                    if len(line) < 4:
                        continue
                    parts = [part.strip() for part in line.split(" - ", 1)]
                    place_name = parts[0]
                    place_settlement = parts[1] if len(parts) > 1 else item.get("settlement", "")
                    expanded.append(
                        {
                            "name": place_name,
                            "settlement": place_settlement,
                            "brief_description": line,
                            "type": item.get("type", "не определено"),
                            "confidence": min(base_confidence, 0.55),
                            "source_fragment": line[:200],
                        }
                    )
                continue

            expanded.append(item)
        return expanded

    def process_file(self, file_path: str, district_folder: str) -> List[Attraction]:
        """Process single DOCX file"""
        self._log(f"\n  Файл: {os.path.basename(file_path)}")
        self.processed_files_count += 1

        # Check cache
        file_hash = self._get_file_hash(file_path)
        cache_key = f"{district_folder}:{os.path.basename(file_path)}"
        cache_meta = self.cache.get("_meta", {})
        cache_items = self.cache.get("items", {})

        if (
            cache_meta.get("version") == self.CACHE_VERSION
            and cache_meta.get("config_signature") == self.config_signature
            and cache_key in cache_items
            and cache_items[cache_key].get("hash") == file_hash
        ):
            self._log(f"    Используем кэш ({len(cache_items[cache_key].get('attractions', []))} объектов)")
            cached_data = cache_items[cache_key].get("attractions", [])
            self.success_files_count += 1
            return [Attraction(**attr) for attr in cached_data]

        # Normalize district name
        district = self.normalizer.normalize(district_folder)

        # Extract content from DOCX/DOC
        text, tables, title, parse_error = self.parser.extract_content(file_path)

        if not text and not tables:
            self._log("    Нет содержимого")
            if parse_error:
                self._log_error(file_path, "parse_error", parse_error)
            return []

        self._log(f"    Извлечено текста: {len(text)} символов, таблиц: {len(tables)}")

        # Extract attractions using AI
        attractions_data = self.ai_client.extract_attractions_from_text(
            text,
            tables,
            district,
            title or os.path.basename(file_path),
        )

        if not attractions_data:
            self._log("    Достопримечательности не извлечены")
            self._log_error(file_path, "extract_error", "AI не извлек объекты из документа")
            return []

        cleaned_attractions_data: List[Dict[str, Any]] = []
        for item in attractions_data:
            cleaned = self._validate_extracted_attraction(item)
            if cleaned:
                cleaned_attractions_data.append(cleaned)

        cleaned_attractions_data = self._expand_list_like_attractions(cleaned_attractions_data, text)

        if not cleaned_attractions_data:
            self._log_error(file_path, "validation_error", "После валидации не осталось валидных объектов")
            return []

        self._log(f"    Найдено объектов: {len(cleaned_attractions_data)}")

        # Enrich each attraction
        attractions: List[Attraction] = []
        for i, attr_data in enumerate(cleaned_attractions_data):
            self._log(f"    Обработка {i+1}/{len(cleaned_attractions_data)}: {attr_data.get('name', 'Unknown')[:50]}")

            # Find settlement in text
            settlement = attr_data.get("settlement", "")
            if not settlement:
                settlement = self.normalizer.find_settlement(district, text)
            settlement, raw_settlement = self._normalize_settlement(district, settlement)

            # Enrich with AI
            enrichment: Dict[str, Any] = {}
            for attempt in range(self.retry_count + 1):
                enrichment = self.ai_client.enrich_attraction_description(attr_data, district)
                paragraph_count = self._count_html_paragraphs(enrichment.get("description_html", ""))
                has_artifacts = self._has_language_artifacts(enrichment.get("description_html", ""))
                if paragraph_count >= self.min_description_paragraphs and not has_artifacts:
                    break
                if attempt < self.retry_count:
                    enrichment = self.ai_client.regenerate_description_strict(
                        attr_data, district, self.min_description_paragraphs
                    )

            # Find photo
            photo_url = ""
            photo_source = ""
            photo_confidence = 0.0
            photo_gallery_urls: List[str] = []
            photo_gallery_sources: List[str] = []
            if not self.skip_photos:
                photo_result = self.image_searcher.find_best_photo(
                    attr_data.get("name", ""),
                    district,
                    settlement,
                )
                photo_url = photo_result.get("primary_url", "")
                photo_source = photo_result.get("primary_source", "")
                photo_confidence = float(photo_result.get("primary_confidence", 0.0))
                photo_gallery_urls = photo_result.get("gallery_urls", [])
                photo_gallery_sources = photo_result.get("gallery_sources", [])

            # Create attraction object
            description_html = enrichment.get("description_html", "")
            paragraph_count = self._count_html_paragraphs(description_html)
            is_low_confidence = attr_data.get("confidence", 0.0) < self.CONFIDENCE_THRESHOLD
            is_list_like = validation.is_list_like_text(description_html)
            has_artifacts = self._has_language_artifacts(description_html)
            if is_low_confidence:
                self.quality_stats["low_confidence"] += 1
            if is_list_like:
                self.quality_stats["list_like_descriptions"] += 1

            description_is_valid = (
                paragraph_count >= self.min_description_paragraphs
                and not has_artifacts
                and not is_low_confidence
                and not is_list_like
            )
            if description_is_valid:
                self.quality_stats["with_min_paragraphs"] += 1
            else:
                self.quality_stats["rejected_descriptions"] += 1
            if photo_url:
                self.quality_stats["with_photo"] += 1
            if attr_data.get("confidence", 0) >= self.CONFIDENCE_THRESHOLD:
                self.quality_stats["high_confidence"] += 1

            attraction = Attraction(
                name=attr_data.get("name", ""),
                district=district,
                settlement=settlement,
                description_html=description_html,
                photo_url=photo_url,
                photo_source=photo_source,
                photo_confidence=photo_confidence,
                additional_info={
                    "type": attr_data.get("type", ""),
                    "brief_description": attr_data.get("brief_description", ""),
                    "source_fragment": attr_data.get("source_fragment", ""),
                    "confidence": attr_data.get("confidence", 0.5),
                    "raw_settlement": raw_settlement,
                    "photo_urls": photo_gallery_urls,
                    "photo_sources": photo_gallery_sources,
                    "description_quality_valid": description_is_valid,
                    "description_is_list_like": is_list_like,
                    "interesting_facts": enrichment.get("interesting_facts", []),
                    "visiting_info": enrichment.get("visiting_info", ""),
                    "historical_period": enrichment.get("historical_period", ""),
                },
            )

            attractions.append(attraction)
            self.processed_count += 1

            # Rate limiting
            self._sleep(0.5)

        # Save to cache
        if attractions:
            self.cache.setdefault("items", {})[cache_key] = {
                "hash": file_hash,
                "attractions": [attr.to_dict() for attr in attractions],
            }
            self._save_cache()
            self.success_files_count += 1

        return attractions

    def process_directory(self, root_folder: str) -> List[Attraction]:
        """Process all DOCX files in directory structure"""
        all_attractions: List[Attraction] = []
        root_path = Path(root_folder)

        # Get all district folders
        district_folders = [d for d in root_path.iterdir() if d.is_dir()]

        self._log(f"\nНайдено папок районов: {len(district_folders)}")
        self._log("=" * 70)

        for idx, district_folder in enumerate(district_folders, 1):
            district_name = district_folder.name
            if self.only_district and self.only_district not in district_name.lower():
                continue
            self._log(f"\n[{idx}/{len(district_folders)}] РАЙОН: {district_name}")
            self._log("-" * 70)

            # Get all DOCX files
            docx_files = list(district_folder.glob("*.docx")) + list(district_folder.glob("*.doc"))

            if not docx_files:
                self._log("  Нет DOCX файлов")
                continue

            self._log(f"  Файлов: {len(docx_files)}")

            # Process each file
            for docx_file in docx_files:
                state_key = str(docx_file.resolve())
                if self.resume and state_key in self.state.get("processed_files", []):
                    self._log("  Пропуск по resume-state")
                    continue
                if self.max_files and self.processed_files_count >= self.max_files:
                    self._log("  Достигнут лимит --max-files")
                    return all_attractions
                try:
                    attractions = self.process_file(str(docx_file), district_name)
                    all_attractions.extend(attractions)
                    self.state.setdefault("processed_files", []).append(state_key)
                    self._save_state()
                except Exception as e:
                    self._log(f"  Ошибка обработки файла: {e}")
                    self._log_error(str(docx_file), "runtime_error", str(e))
                    self._save_errors()

                # Save progress every 5 files
                if len(all_attractions) % 5 == 0:
                    self.save_progress(
                        all_attractions,
                        str(self.output_dir / "progress_backup.json"),
                    )

        return all_attractions

    def save_progress(self, attractions: List[Attraction], filename: str) -> None:
        """Save intermediate results"""
        data = [attr.to_dict() for attr in attractions]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._log(f"\n  Прогресс сохранен в {filename} ({len(attractions)} объектов)")

    def export_json(self, attractions: List[Attraction], output_file: str) -> None:
        """Export final results to JSON"""
        data, quality = build_export_payload(
            attractions,
            quality_stats=self.quality_stats,
            processed_files_count=self.processed_files_count,
            success_files_count=self.success_files_count,
            errors_count=len(self.errors),
            ai_model=self.ai_client.model,
            ai_requests=self.ai_client.request_count,
            estimated_tokens=self.ai_client.token_usage,
            cache_version=self.CACHE_VERSION,
            prompt_version=self.ai_client.prompt_version,
        )

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        out_path = Path(output_file)
        quality_file = str(out_path.with_name(f"{out_path.stem}_quality_report.json"))
        with open(quality_file, "w", encoding="utf-8") as f:
            json.dump(quality, f, ensure_ascii=False, indent=2)
        self._save_errors()

        self._log(f"\n{'='*70}")
        self._log("ЭКСПОРТ ЗАВЕРШЕН")
        self._log(f"{'='*70}")
        self._log(f"Всего достопримечательностей: {len(attractions)}")
        self._log(f"Районов: {len(data.get('by_district', {}))}")
        self._log(f"Файл: {output_file}")
        self._log(f"Quality report: {quality_file}")
        self._log(f"С фото: {quality['attractions_with_photo_percent']}%")
        self._log(
            f"Описание >= {self.min_description_paragraphs} абз.: {quality['descriptions_with_min_paragraphs_percent']}%"
        )
        self._log(f"Высокая уверенность: {quality['high_confidence_percent']}%")
        self._log(f"{'='*70}")
