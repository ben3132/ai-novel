"""从证据数据库生成逐作品文本质量报告，不修改原文。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path


CHAPTER_NO_RE = re.compile(r"第([零〇一二三四五六七八九十百千万两\d]+)章")


def chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = section = number = 0
    try:
        for char in value:
            if char in digits:
                number = digits[char]
            elif char in units:
                unit = units[char]
                if unit == 10000:
                    section = (section + number) * unit
                    total += section; section = number = 0
                else:
                    section += (number or 1) * unit
                    number = 0
            else:
                return None
        return total + section + number
    except Exception:
        return None


def audit(database: Path) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    works = []
    for work in connection.execute("SELECT * FROM works ORDER BY sequence_no"):
        chapters = connection.execute(
            "SELECT * FROM chapters WHERE work_id=? ORDER BY chapter_index", (work["work_id"],)
        ).fetchall()
        titles = [row["title"] for row in chapters if row["title"]]
        numbers = []
        for title in titles:
            match = CHAPTER_NO_RE.search(title)
            number = chinese_number(match.group(1)) if match else None
            if number is not None:
                numbers.append(number)
        number_counts = Counter(numbers)
        missing = []
        if numbers:
            present = set(numbers)
            missing = [number for number in range(min(numbers), max(numbers) + 1) if number not in present][:200]
        duplicate_titles = [title for title, count in Counter(titles).items() if count > 1]
        duplicate_numbers = [number for number, count in number_counts.items() if count > 1]
        tiny = [row["chapter_id"] for row in chapters if row["char_count"] < 200]
        huge = [row["chapter_id"] for row in chapters if row["char_count"] > 50000]
        replacement_chars = connection.execute(
            """SELECT COALESCE(SUM(LENGTH(u.text)-LENGTH(REPLACE(u.text,'�',''))),0)
               FROM text_units u JOIN source_works sw ON sw.source_id=u.source_id WHERE sw.work_id=?""",
            (work["work_id"],),
        ).fetchone()[0]
        chapter_hashes = Counter()
        for chapter in chapters:
            digest = hashlib.sha256()
            for row in connection.execute(
                "SELECT text FROM text_units WHERE source_id=? AND chapter_index=? ORDER BY sequence_no",
                (chapter["source_id"], chapter["chapter_index"]),
            ):
                digest.update(row[0].encode("utf-8")); digest.update(b"\n")
            chapter_hashes[digest.hexdigest()] += 1
        works.append({
            "work_id": work["work_id"], "title": work["title"],
            "sections": len(chapters), "front_matter": sum(row["section_type"] == "front_matter" for row in chapters),
            "numbered_chapters": len(numbers), "number_min": min(numbers) if numbers else None,
            "number_max": max(numbers) if numbers else None, "missing_numbers": missing,
            "duplicate_numbers": duplicate_numbers, "duplicate_titles": duplicate_titles[:100],
            "tiny_chapters": tiny[:100], "huge_chapters": huge[:100],
            "duplicate_chapter_content": sum(count - 1 for count in chapter_hashes.values() if count > 1),
            "replacement_characters": replacement_chars,
        })
    connection.close()
    return {"works": works}


def main() -> int:
    parser = argparse.ArgumentParser(description="小说文本质量审计")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.database.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "works": len(report["works"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
