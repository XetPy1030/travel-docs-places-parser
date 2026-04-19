# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI


def parse_json_response_from_llm(response: str, log_fn: Optional[Callable[..., None]] = None) -> List[Dict[str, Any]]:
    """Разбор JSON-массива объектов из ответа LLM (без сетевых вызовов)."""
    log = log_fn or print
    try:
        # Find JSON array in response
        json_match = re.search(r"\[\s*\{.*\}\s*\]", response, re.DOTALL)
        if json_match:
            attractions = json.loads(json_match.group())
            return attractions
        # Try to parse entire response
        attractions = json.loads(response)
        return attractions
    except json.JSONDecodeError as e:
        log(f"  JSON parse error: {e}")
        # Try to find any JSON-like structure
        try:
            # Look for objects
            obj_pattern = r"\{[^{}]*\"name\"[^{}]*\}"
            matches = re.findall(obj_pattern, response, re.DOTALL)
            if matches:
                # Try to parse each match
                result: List[Dict[str, Any]] = []
                for match in matches:
                    try:
                        obj = json.loads(match)
                        result.append(obj)
                    except Exception:
                        pass
                return result
        except Exception:
            pass
        return []


class OpenRouterClient:
    """Client for OpenRouter AI API"""

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-3.1-70b-instruct",
        max_retries: int = 2,
        client: Optional[OpenAI] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        log_fn: Optional[Callable[..., None]] = None,
        error_hook: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model
        self.request_count = 0
        self.token_usage = 0
        self.prompt_version = "v2-structured-extraction"
        self.max_retries = max(0, max_retries)
        self.failed_requests = 0
        self._sleep = sleep_fn or time.sleep
        self._log = log_fn or print
        self._error_hook = error_hook

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> str:
        """Send chat completion request"""
        self.request_count += 1
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                # Track token usage
                if hasattr(response, "usage") and response.usage:
                    self.token_usage += response.usage.total_tokens

                return response.choices[0].message.content or ""

            except Exception as e:
                last_error = str(e)
                self._log(f"  OpenRouter error: {e}")
                if attempt < self.max_retries:
                    self._sleep(min(2 + attempt, 4))

        self.failed_requests += 1
        if self._error_hook:
            self._error_hook(last_error or "Unknown OpenRouter error")
        return ""

    def extract_attractions_from_text(
        self,
        text: str,
        tables: List[Dict[str, Any]],
        district: str,
        filename: str,
    ) -> List[Dict[str, Any]]:
        """
        Use AI to extract attractions from document text and tables
        """
        # Prepare tables text
        tables_text = ""
        for table in tables:
            tables_text += "\nТАБЛИЦА:\n"
            for row in table.get("rows", []):
                tables_text += " | ".join(str(cell) for cell in row) + "\n"

        prompt = f"""
Вы эксперт по извлечению информации о достопримечательностях из документов о районах Татарстана.

РАЙОН: {district}
ФАЙЛ: {filename}

ТЕКСТ ДОКУМЕНТА:
{text}

{tables_text}

ЗАДАЧА:
Извлеките ВСЕ достопримечательности, памятники, музеи, храмы, мечети, природные объекты из этого документа.

Для КАЖДОГО объекта укажите:
1. name - точное название достопримечательности
2. settlement - населенный пункт (село, город, поселок), где находится (если указан)
3. brief_description - краткое описание 1-2 предложения ТОЛЬКО из документа
4. type - тип объекта (музей, памятник, храм, мечеть, природный объект, усадьба и т.д.)
5. confidence - число от 0 до 1, насколько уверены в корректности извлечения
6. source_fragment - короткая цитата (до 200 символов) из документа, подтверждающая объект

Верните ТОЛЬКО валидный JSON массив в формате:
[
  {{
    "name": "Название достопримечательности",
    "settlement": "Название населенного пункта",
    "brief_description": "Краткое описание",
    "type": "категория",
    "confidence": 0.82,
    "source_fragment": "Фрагмент текста документа"
  }}
]

Если достопримечательностей не найдено, верните пустой массив [].
Если документ содержит только список без деталей, извлеките что можете.
Если в документе одна большая достопримечательность - извлеките ее.
"""

        messages = [
            {
                "role": "system",
                "content": "Вы полезный помощник, который извлекает структурированные данные из документов. Всегда отвечайте валидным JSON.",
            },
            {"role": "user", "content": prompt},
        ]

        response = self.chat_completion(messages, max_tokens=3500)

        # Parse JSON from response
        attractions = parse_json_response_from_llm(response, log_fn=self._log)

        if not attractions and text.strip():
            # Fallback: create single attraction from document
            attractions = [
                {
                    "name": filename.replace(".docx", "").replace(".doc", ""),
                    "settlement": "",
                    "brief_description": text[:500] if text else "Информация о достопримечательности",
                    "type": "не определено",
                    "confidence": 0.35,
                    "source_fragment": text[:200] if text else "",
                }
            ]

        return attractions if attractions else []

    def enrich_attraction_description(self, attraction: Dict[str, Any], district: str) -> Dict[str, Any]:
        """
        Enrich attraction with detailed HTML description using AI
        """
        name = attraction.get("name", "")
        settlement = attraction.get("settlement", "")
        brief = attraction.get("brief_description", "")
        attr_type = attraction.get("type", "")

        location_info = f"{settlement}, {district}" if settlement else district

        prompt = f"""
Вы эксперт-краевед по Республике Татарстан.

ДОСТОПРИМЕЧАТЕЛЬНОСТЬ: {name}
РАСПОЛОЖЕНИЕ: {location_info}, Республика Татарстан
ТИП: {attr_type}
КРАТКАЯ ИНФОРМАЦИЯ: {brief}

ЗАДАЧА:
1. Создайте подробное описание этой достопримечательности (3-4 абзаца в формате HTML)
2. Включите историческую справку, архитектурные особенности, культурную значимость
3. Если точной информации нет, дайте общий контекст о подобных объектах в Татарстане
4. Пишите на русском языке
5. Используйте правильную HTML разметку с тегами <p>
6. Добавьте интересные факты если возможно

Верните JSON:
{{
  "description_html": "<p>Первый абзац...</p><p>Второй абзац...</p><p>Третий абзац...</p>",
  "interesting_facts": ["Интересный факт 1", "Интересный факт 2"],
  "visiting_info": "Информация о посещении (если есть)",
  "historical_period": "Исторический период/век"
}}
"""

        messages = [
            {"role": "system", "content": "Вы знающий краевед и гид. Предоставляйте точную, увлекательную информацию."},
            {"role": "user", "content": prompt},
        ]

        response = self.chat_completion(messages, max_tokens=2500)

        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                enrichment = json.loads(json_match.group())
                return enrichment
        except Exception:
            pass

        # Fallback: generate simple HTML from brief description
        paragraphs: List[str] = []
        if brief:
            sentences = re.split(r"[.!?]+", brief)
            para1 = ". ".join(s.strip() for s in sentences[:3] if s.strip())
            para2 = ". ".join(s.strip() for s in sentences[3:6] if s.strip())
            para3 = f"Данная достопримечательность расположена в {location_info} районе Республики Татарстан и представляет культурно-историческую ценность для региона."

            if para1:
                paragraphs.append(f"<p>{para1}.</p>")
            if para2:
                paragraphs.append(f"<p>{para2}.</p>")
            paragraphs.append(f"<p>{para3}</p>")
        else:
            paragraphs = [
                f"<p>{name} - достопримечательность {location_info} района Республики Татарстан.</p>",
                f"<p>Объект представляет интерес для туристов и краеведов, изучающих историю и культуру региона.</p>",
                f"<p>Рекомендуется к посещению всем, кто интересуется историческим наследием Татарстана.</p>",
            ]

        return {
            "description_html": "".join(paragraphs),
            "interesting_facts": [],
            "visiting_info": "",
            "historical_period": "",
        }

    def regenerate_description_strict(
        self,
        attraction: Dict[str, Any],
        district: str,
        min_paragraphs: int = 2,
    ) -> Dict[str, Any]:
        """Regenerate HTML description with strict quality constraints"""
        name = attraction.get("name", "")
        settlement = attraction.get("settlement", "")
        brief = attraction.get("brief_description", "")
        attr_type = attraction.get("type", "")
        location_info = f"{settlement}, {district}" if settlement else district

        prompt = f"""
Сформируйте качественное и нейтральное описание достопримечательности.

Название: {name}
Локация: {location_info}, Республика Татарстан
Тип: {attr_type}
Известные данные: {brief}

Требования:
- Только русский язык
- Минимум {min_paragraphs} абзаца в HTML <p>...</p>
- Без вымышленных деталей, только осторожные формулировки при нехватке данных
- Без английских слов внутри русских предложений

Верните JSON:
{{
  "description_html": "<p>...</p><p>...</p>",
  "interesting_facts": [],
  "visiting_info": "",
  "historical_period": ""
}}
"""
        messages = [
            {"role": "system", "content": "Верни строго JSON. Следуй требованиям к качеству текста."},
            {"role": "user", "content": prompt},
        ]
        response = self.chat_completion(messages, max_tokens=1500, temperature=0.2)
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        return self.enrich_attraction_description(attraction, district)
