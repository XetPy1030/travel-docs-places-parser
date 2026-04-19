"""Пакет приложения: парсинг DOCX → JSON с OpenRouter и поиском изображений."""

from app.models import Attraction
from app.processor import AttractionProcessor

__all__ = ["Attraction", "AttractionProcessor"]
