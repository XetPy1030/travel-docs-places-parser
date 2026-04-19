# -*- coding: utf-8 -*-
"""Точка входа CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.processor import AttractionProcessor


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Парсинг достопримечательностей из DOCX файлов")
    parser.add_argument("--input", "-i", required=True, help="Папка с подпапками районов")
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Каталог для кэша, state, ошибок и относительного --output",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="attractions.json",
        help="Выходной JSON (если путь не абсолютный — внутри --output-dir)",
    )
    parser.add_argument("--api-key", required=True, help="OpenRouter API ключ")
    parser.add_argument(
        "--model",
        default="meta-llama/llama-3.1-70b-instruct",
        help="Модель OpenRouter",
    )
    parser.add_argument(
        "--districts",
        "-d",
        help="JSON файл со списком районов и населенных пунктов",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Ограничить количество обрабатываемых файлов (0 - без лимита)",
    )
    parser.add_argument(
        "--only-district",
        default="",
        help="Обрабатывать только районы, содержащие эту строку",
    )
    parser.add_argument("--skip-photos", action="store_true", help="Пропустить поиск фотографий")
    parser.add_argument(
        "--min-description-paragraphs",
        type=int,
        default=2,
        help="Минимум абзацев в HTML-описании",
    )
    parser.add_argument(
        "--retry-count",
        type=int,
        default=2,
        help="Количество повторов для регенерации описания",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Продолжить обработку по processing_state.json в --output-dir",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_arg = Path(args.output)
    output_path = out_arg if out_arg.is_absolute() else output_dir / out_arg
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path_str = str(output_path)

    # Load districts data if provided
    districts_json = None
    if args.districts and os.path.exists(args.districts):
        with open(args.districts, "r", encoding="utf-8") as f:
            districts_json = f.read()
        print(f"Загружен список районов из {args.districts}")

    # Initialize processor
    print(f"\n{'='*70}")
    print("ПАРСЕР ДОСТОПРИМЕЧАТЕЛЬНОСТЕЙ ТАТАРСТАНА")
    print(f"{'='*70}")
    print(f"Входная папка: {args.input}")
    print(f"Каталог вывода: {output_dir}")
    print(f"Выходной файл: {output_path_str}")
    print(f"Модель AI: {args.model}")
    print(f"Поиск фото: {'выкл' if args.skip_photos else 'вкл'}")
    print(f"Resume: {'да' if args.resume else 'нет'}")
    print(f"{'='*70}\n")

    processor = AttractionProcessor(
        args.api_key,
        districts_json,
        model=args.model,
        skip_photos=args.skip_photos,
        min_description_paragraphs=max(1, args.min_description_paragraphs),
        retry_count=max(0, args.retry_count),
        resume=args.resume,
        max_files=max(0, args.max_files),
        only_district=args.only_district,
        output_dir=str(output_dir),
    )

    # Process all files
    attractions = processor.process_directory(args.input)

    if not attractions:
        print("\n⚠️  Достопримечательности не найдены!")
        return

    # Export results
    processor.export_json(attractions, output_path_str)

    print(f"\nВсего обработано: {processor.processed_count} достопримечательностей")
    print(f"Запросов к AI: {processor.ai_client.request_count}")
    print(f"Использовано токенов: ~{processor.ai_client.token_usage}")
