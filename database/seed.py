#!/usr/bin/env python3
"""
Quran WBW – PostgreSQL seeder
==============================
Fetches all Quran data from the quranwbw CDN and populates the PostgreSQL
database whose schema is defined in schema.sql.

Usage
-----
    pip install -r requirements.txt
    python seed.py --dsn "postgresql://user:password@localhost:5432/quran"

The DATABASE_URL environment variable is used when --dsn is not supplied.

What is seeded
--------------
1. chapters          – 114 surahs (hardcoded from quranMeta.js)
2. verses            – 6,236 ayahs with page/juz metadata from the CDN
3. words             – word-by-word Arabic text (Uthmanic, font-id 1)
4. word_translations – every word translated into all 20 word languages
5. verse_translations – full-ayah translations for every resource listed
                        in verse_translation_resources

CDN base URL: https://static.quranwbw.com/data/v4
"""

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import aiohttp
import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CDN configuration
# ---------------------------------------------------------------------------
CDN = "https://static.quranwbw.com/data/v4"

# Arabic Uthmanic font-id 1, version 5 (matches selectableFontTypes[1] in
# src/data/options.js).  Only one Arabic source is needed for word storage.
ARABIC_FONT_ID = 1
ARABIC_VERSION = 5

# Default transliteration (Normal), id=1
TRANSLITERATION_ID = 1
TRANSLITERATION_VERSION = 1

# Word-translation language ids and CDN versions
# (matches selectableWordTranslations in src/data/options.js)
WORD_TRANSLATION_LANGUAGES: dict[int, int] = {
    1: 4,   # English
    2: 1,   # Urdu
    3: 1,   # Hindi
    4: 1,   # Indonesian
    5: 1,   # Bangla
    6: 1,   # Turkish
    7: 1,   # Tamil
    8: 1,   # German
    11: 1,  # French
    12: 1,  # Malayalam (Amani Thafseer)
    13: 1,  # Malayalam (Quran Lalithasaram)
    14: 1,  # Chinese (Traditional)
    15: 1,  # Chinese (Zhuyin)
    16: 1,  # Chinese (Simplified)
    17: 1,  # Chinese (Pinyin)
    18: 1,  # Divehi
    19: 1,  # Persian
    20: 1,  # Sindhi
    21: 1,  # Albanian
    22: 1,  # Sign Language
}

# Verse-translation resource ids and CDN versions
# (matches selectableVerseTranslations in src/data/options.js)
VERSE_TRANSLATION_RESOURCES: dict[int, int] = {
    88: 1,   # Albanian – Hasan Efendi Nahi
    161: 1,  # Bangla – Taisirul Quran
    163: 1,  # Bangla – Sheikh Mujibur Rahman
    162: 1,  # Bangla – Rawai Al-bayan
    213: 1,  # Bangla – Dr. Abu Bakr Muhammad Zakaria
    56: 1,   # Chinese – Ma Jain
    109: 1,  # Chinese – Muhammad Makin
    86: 1,   # Divehi – Office of the president of Maldives
    840: 1,  # Divehi – Abu Bakr Ibrahim Ali
    131: 1,  # English – The Clear Quran
    20: 1,   # English – Saheeh International
    84: 1,   # English – Mufti Taqi Usmani
    85: 1,   # English – Abdel Haleem
    95: 1,   # English – Abul Alaa Maududi
    19: 1,   # English – Pickthall
    22: 1,   # English – Yusuf Ali
    203: 1,  # English – Hilali & Khan
    779: 1,  # French – Rashid Maash
    136: 1,  # French – Montada Islamic Foundation
    31: 1,   # French – Muhammad Hamidullah
    208: 1,  # German – Abu Reda Muhammad ibn Ahmad
    27: 1,   # German – Frank Bubenheim and Nadeem
    122: 1,  # Hindi – Maulana Azizul Haque al-Umari
    134: 1,  # Indonesian – King Fahad Quran Complex
    33: 1,   # Indonesian – Islamic affairs ministry
    141: 1,  # Indonesian – The Sabiq company
    224: 1,  # Malayalam – Abdul-Hamid Haidar & Kanhi Muhammad
    80: 1,   # Malayalam – Muhammad Karakunnu
    37: 1,   # Malayalam – Abdul Hameed and Kunhi
    135: 1,  # Persian – IslamHouse.com
    29: 1,   # Persian – Hussein Taji Kal Dari
    79: 1,   # Russian – Abu Adel
    78: 1,   # Russian – Ministry of Awqaf, Egypt
    45: 1,   # Russian – Elmir Kuliev
    238: 1,  # Sindhi – Taj Mehmood Amroti
    229: 1,  # Tamil – Sheikh Omar Sharif
    50: 1,   # Tamil – Jan Trust Foundation
    133: 1,  # Tamil – Abdul Hameed Baqavi
    1: 2,    # Transliteration – Simple Tajweed
    3: 2,    # Transliteration – Syllables
    57: 2,   # Transliteration – Normal
    4: 1,    # Transliteration – Advanced Tajweed
    210: 1,  # Turkish – Dar Al-Salam Center
    77: 1,   # Turkish – Diyanet
    52: 1,   # Turkish – Elmalili Hamdi Yazir
    112: 1,  # Turkish – Shaban Britch
    124: 1,  # Turkish – Muslim Shahin
    156: 1,  # Urdu – Fe Zilal al-Quran
    97: 1,   # Urdu – Tafheem Ul Quran
    234: 1,  # Urdu – Fatah Muhammad Jalandhari
    158: 1,  # Urdu – Bayan al-Quran
    151: 1,  # Urdu – Shaykh al-Hind Mahmud al-Hasan
    54: 1,   # Urdu – Maulana Muhammad Junagarhi
    819: 1,  # Urdu – Maulana Wahiduddin Khan
    831: 1,  # Urdu – Abul Alaa Maududi (Roman Urdu)
}

# ---------------------------------------------------------------------------
# Chapter metadata  (from src/data/quranMeta.js)
# Tuple: (id, arabic, translation, transliteration, verse_count, revelation_type)
# revelation_type: 1 = Meccan, 2 = Medinan
# ---------------------------------------------------------------------------
CHAPTERS = [
    (1,   "الفاتحة",   "The Opening",                "Al Faatiha",        7,   1),
    (2,   "البقرة",    "The Cow",                     "Al Baqara",         286, 2),
    (3,   "آل عمران",  "The Family of Imraan",        "Aal i Imraan",      200, 2),
    (4,   "النساء",    "The Women",                   "An Nisaa",          176, 2),
    (5,   "المائدة",   "The Table",                   "Al Maaida",         120, 2),
    (6,   "الأنعام",   "The Cattle",                  "Al An'aam",         165, 1),
    (7,   "الأعراف",   "The Heights",                 "Al A'raaf",         206, 1),
    (8,   "الأنفال",   "The Spoils of War",           "Al Anfaal",         75,  2),
    (9,   "التوبة",    "The Repentance",              "At Tawba",          129, 2),
    (10,  "يونس",      "Jonas",                       "Yunus",             109, 1),
    (11,  "هود",       "Hud",                         "Hud",               123, 1),
    (12,  "يوسف",      "Joseph",                      "Yusuf",             111, 1),
    (13,  "الرعد",     "The Thunder",                 "Ar Ra'd",           43,  2),
    (14,  "ابراهيم",   "Abraham",                     "Ibrahim",           52,  1),
    (15,  "الحجر",     "The Rock",                    "Al Hijr",           99,  1),
    (16,  "النحل",     "The Bee",                     "An Nahl",           128, 1),
    (17,  "الإسراء",   "The Night Journey",           "Al Israa",          111, 1),
    (18,  "الكهف",     "The Cave",                    "Al Kahf",           110, 1),
    (19,  "مريم",      "Mary",                        "Maryam",            98,  1),
    (20,  "طه",        "Taa Haa",                     "Taa Haa",           135, 1),
    (21,  "الأنبياء",  "The Prophets",                "Al Anbiyaa",        112, 1),
    (22,  "الحج",      "The Pilgrimage",              "Al Hajj",           78,  2),
    (23,  "المؤمنون",  "The Believers",               "Al Muminoon",       118, 1),
    (24,  "النور",     "The Light",                   "An Noor",           64,  2),
    (25,  "الفرقان",   "The Criterion",               "Al Furqaan",        77,  1),
    (26,  "الشعراء",   "The Poets",                   "Ash Shu'araa",      227, 1),
    (27,  "النمل",     "The Ant",                     "An Naml",           93,  1),
    (28,  "القصص",     "The Stories",                 "Al Qasas",          88,  1),
    (29,  "العنكبوت",  "The Spider",                  "Al Ankaboot",       69,  1),
    (30,  "الروم",     "The Romans",                  "Ar Room",           60,  1),
    (31,  "لقمان",     "Luqman",                      "Luqman",            34,  1),
    (32,  "السجدة",    "The Prostration",             "As Sajda",          30,  1),
    (33,  "الأحزاب",   "The Clans",                   "Al Ahzaab",         73,  2),
    (34,  "سبإ",       "Sheba",                       "Saba",              54,  1),
    (35,  "فاطر",      "The Originator",              "Faatir",            45,  1),
    (36,  "يس",        "Yaseen",                      "Yaseen",            83,  1),
    (37,  "الصافات",   "Those drawn up in Ranks",     "As Saaffaat",       182, 1),
    (38,  "ص",         "The letter Saad",             "Saad",              88,  1),
    (39,  "الزمر",     "The Groups",                  "Az Zumar",          75,  1),
    (40,  "غافر",      "The Forgiver",                "Al Ghaafir",        85,  1),
    (41,  "فصلت",      "Explained in detail",         "Fussilat",          54,  1),
    (42,  "الشورى",    "Consultation",                "Ash Shura",         53,  1),
    (43,  "الزخرف",    "Ornaments of gold",           "Az Zukhruf",        89,  1),
    (44,  "الدخان",    "The Smoke",                   "Ad Dukhaan",        59,  1),
    (45,  "الجاثية",   "Crouching",                   "Al Jaathiya",       37,  1),
    (46,  "الأحقاف",   "The Dunes",                   "Al Ahqaf",          35,  1),
    (47,  "محمد",      "Muhammad",                    "Muhammad",          38,  2),
    (48,  "الفتح",     "The Victory",                 "Al Fath",           29,  2),
    (49,  "الحجرات",   "The Inner Apartments",        "Al Hujuraat",       18,  2),
    (50,  "ق",         "The letter Qaaf",             "Qaaf",              45,  1),
    (51,  "الذاريات",  "The Winnowing Winds",         "Adh Dhaariyat",     60,  1),
    (52,  "الطور",     "The Mount",                   "At Tur",            49,  1),
    (53,  "النجم",     "The Star",                    "An Najm",           62,  1),
    (54,  "القمر",     "The Moon",                    "Al Qamar",          55,  1),
    (55,  "الرحمن",    "The Beneficent",              "Ar Rahmaan",        78,  2),
    (56,  "الواقعة",   "The Inevitable",              "Al Waaqia",         96,  1),
    (57,  "الحديد",    "The Iron",                    "Al Hadid",          29,  2),
    (58,  "المجادلة",  "The Pleading Woman",          "Al Mujaadila",      22,  2),
    (59,  "الحشر",     "The Exile",                   "Al Hashr",          24,  2),
    (60,  "الممتحنة",  "She Who Is Examined",         "Al Mumtahana",      13,  2),
    (61,  "الصف",      "The Ranks",                   "As Saff",           14,  2),
    (62,  "الجمعة",    "Friday",                      "Al Jumu'a",         11,  2),
    (63,  "المنافقون", "The Hypocrites",              "Al Munaafiqoon",    11,  2),
    (64,  "التغابن",   "Mutual Disillusion",          "At Taghaabun",      18,  2),
    (65,  "الطلاق",    "Divorce",                     "At Talaaq",         12,  2),
    (66,  "التحريم",   "The Prohibition",             "At Tahrim",         12,  2),
    (67,  "الملك",     "The Sovereignty",             "Al Mulk",           30,  1),
    (68,  "القلم",     "The Pen",                     "Al Qalam",          52,  1),
    (69,  "الحاقة",    "The Reality",                 "Al Haaqqa",         52,  1),
    (70,  "المعارج",   "The Ascending Stairways",     "Al Ma'aarij",       44,  1),
    (71,  "نوح",       "Noah",                        "Nooh",              28,  1),
    (72,  "الجن",      "The Jinn",                    "Al Jinn",           28,  1),
    (73,  "المزمل",    "The Enshrouded One",          "Al Muzzammil",      20,  1),
    (74,  "المدثر",    "The Cloaked One",             "Al Muddaththir",    56,  1),
    (75,  "القيامة",   "The Resurrection",            "Al Qiyaama",        40,  1),
    (76,  "الانسان",   "Man",                         "Al Insaan",         31,  2),
    (77,  "المرسلات",  "The Emissaries",              "Al Mursalaat",      50,  1),
    (78,  "النبإ",     "The Announcement",            "An Naba",           40,  1),
    (79,  "النازعات",  "Those who drag forth",        "An Naazi'aat",      46,  1),
    (80,  "عبس",       "He frowned",                  "Abasa",             42,  1),
    (81,  "التكوير",   "The Overthrowing",            "At Takwir",         29,  1),
    (82,  "الإنفطار",  "The Cleaving",                "Al Infitaar",       19,  1),
    (83,  "المطففين",  "Defrauding",                  "Al Mutaffifin",     36,  1),
    (84,  "الإنشقاق",  "The Splitting Open",          "Al Inshiqaaq",      25,  1),
    (85,  "البروج",    "The Constellations",          "Al Burooj",         22,  1),
    (86,  "الطارق",    "The Morning Star",            "At Taariq",         17,  1),
    (87,  "الأعلى",    "The Most High",               "Al A'laa",          19,  1),
    (88,  "الغاشية",   "The Overwhelming",            "Al Ghaashiya",      26,  1),
    (89,  "الفجر",     "The Dawn",                    "Al Fajr",           30,  1),
    (90,  "البلد",     "The City",                    "Al Balad",          20,  1),
    (91,  "الشمس",     "The Sun",                     "Ash Shams",         15,  1),
    (92,  "الليل",     "The Night",                   "Al Lail",           21,  1),
    (93,  "الضحى",     "The Morning Hours",           "Ad Dhuhaa",         11,  1),
    (94,  "الشرح",     "The Consolation",             "Ash Sharh",         8,   1),
    (95,  "التين",     "The Fig",                     "At Tin",            8,   1),
    (96,  "العلق",     "The Clot",                    "Al Alaq",           19,  1),
    (97,  "القدر",     "The Power, Fate",             "Al Qadr",           5,   1),
    (98,  "البينة",    "The Evidence",                "Al Bayyina",        8,   2),
    (99,  "الزلزلة",   "The Earthquake",              "Az Zalzala",        8,   2),
    (100, "العاديات",  "The Chargers",                "Al Aadiyaat",       11,  1),
    (101, "القارعة",   "The Calamity",                "Al Qaari'a",        11,  1),
    (102, "التكاثر",   "Competition",                 "At Takaathur",      8,   1),
    (103, "العصر",     "The Declining Day",           "Al Asr",            3,   1),
    (104, "الهمزة",    "The Traducer",                "Al Humaza",         9,   1),
    (105, "الفيل",     "The Elephant",                "Al Fil",            5,   1),
    (106, "قريش",      "Quraysh",                     "Quraish",           4,   1),
    (107, "الماعون",   "Almsgiving",                  "Al Maa'un",         7,   1),
    (108, "الكوثر",    "Abundance",                   "Al Kawthar",        3,   1),
    (109, "الكافرون",  "The Disbelievers",            "Al Kaafiroon",      6,   1),
    (110, "النصر",     "Divine Support",              "An Nasr",           3,   2),
    (111, "المسد",     "The Palm Fibre",              "Al Masad",          5,   1),
    (112, "الإخلاص",   "Sincerity",                   "Al Ikhlaas",        4,   1),
    (113, "الفلق",     "The Dawn",                    "Al Falaq",          5,   1),
    (114, "الناس",     "Mankind",                     "An Naas",           6,   1),
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
async def fetch_json(session: aiohttp.ClientSession, url: str) -> Any:
    """Fetch a JSON endpoint; raise on non-200."""
    async with session.get(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return await resp.json(content_type=None)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_verse_key(raw_key: str) -> tuple[int, int]:
    """Convert a 'chapter:verse' string to (int, int)."""
    chapter_str, verse_str = raw_key.split(":", 1)
    return int(chapter_str), int(verse_str)


def normalise_verse_translation(data: Any) -> dict[tuple[int, int], str]:
    """
    Handle two common CDN formats for verse translations:
      • flat dict  { "1:1": "text", ... }
      • nested     { "1": { "1": "text", ... }, ... }
    Returns a dict keyed by (chapter_id, verse_num).
    """
    result: dict[tuple[int, int], str] = {}
    if not data:
        return result
    first_key = next(iter(data))
    if ":" in str(first_key):
        # flat format
        for key, text in data.items():
            result[parse_verse_key(key)] = str(text) if text else ""
    else:
        # nested format
        for chapter_str, verses in data.items():
            chapter_id = int(chapter_str)
            if isinstance(verses, dict):
                for verse_str, text in verses.items():
                    result[(chapter_id, int(verse_str))] = str(text) if text else ""
    return result


# ---------------------------------------------------------------------------
# Database seeding
# ---------------------------------------------------------------------------
async def seed_chapters(conn: asyncpg.Connection) -> None:
    log.info("Seeding chapters …")
    await conn.executemany(
        """
        INSERT INTO chapters (id, arabic, translation, transliteration,
                              verse_count, revelation_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (id) DO NOTHING
        """,
        CHAPTERS,
    )
    log.info("  → %d chapters inserted/skipped", len(CHAPTERS))


async def seed_verses_and_words(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
) -> None:
    """Fetch Arabic word data + verse meta and populate verses and words."""
    log.info("Fetching Arabic word data (font-id %d, v%d) …", ARABIC_FONT_ID, ARABIC_VERSION)
    arabic_data: dict = await fetch_json(
        session,
        f"{CDN}/words-data/arabic/{ARABIC_FONT_ID}.json?version={ARABIC_VERSION}",
    )

    log.info("Fetching verse metadata …")
    meta_data: dict = await fetch_json(
        session, f"{CDN}/meta/verseKeyData.json?version=2"
    )

    log.info("Fetching word transliterations (id %d, v%d) …", TRANSLITERATION_ID, TRANSLITERATION_VERSION)
    translit_data: dict = await fetch_json(
        session,
        f"{CDN}/words-data/transliterations/{TRANSLITERATION_ID}.json"
        f"?version={TRANSLITERATION_VERSION}",
    )

    verses_rows: list[tuple] = []
    words_rows: list[tuple] = []

    for chapter_str, chapter_verses in arabic_data.items():
        chapter_id = int(chapter_str)
        for verse_str, verse_payload in chapter_verses.items():
            verse_num = int(verse_str)
            # verse_payload = [[arabic_words], [line_numbers], [end_icons]]
            arabic_words: list[str] = verse_payload[0] if verse_payload else []
            line_numbers: list = verse_payload[1] if len(verse_payload) > 1 else []

            verse_key = f"{chapter_id}:{verse_num}"
            meta = meta_data.get(verse_key, {})
            page = meta.get("page")
            juz = meta.get("juz")

            verses_rows.append(
                (chapter_id, verse_num, page, juz, len(arabic_words))
            )

            # transliterations for this verse
            translit_verse = (
                translit_data.get(chapter_str, {})
                .get(verse_str, [[]])[0]
            )

            for pos, arabic_text in enumerate(arabic_words, start=1):
                line_num = line_numbers[pos - 1] if pos - 1 < len(line_numbers) else None
                translit = (
                    translit_verse[pos - 1]
                    if pos - 1 < len(translit_verse)
                    else None
                )
                words_rows.append(
                    (chapter_id, verse_num, pos, arabic_text, translit, line_num)
                )

    log.info("Inserting %d verses …", len(verses_rows))
    await conn.executemany(
        """
        INSERT INTO verses (chapter_id, verse_num, page, juz, word_count)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (chapter_id, verse_num) DO NOTHING
        """,
        verses_rows,
    )

    log.info("Inserting %d words …", len(words_rows))
    # Use copy_records_to_table for bulk performance
    await conn.copy_records_to_table(
        "words",
        records=words_rows,
        columns=["chapter_id", "verse_num", "word_position",
                 "arabic_text", "transliteration", "line_num"],
    )
    log.info("  → words inserted")


async def seed_word_translations(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
) -> None:
    """Fetch and insert word-by-word translations for every language."""
    for lang_id, version in WORD_TRANSLATION_LANGUAGES.items():
        url = f"{CDN}/words-data/translations/{lang_id}.json?version={version}"
        log.info("Fetching word translations lang_id=%d …", lang_id)
        try:
            data: dict = await fetch_json(session, url)
        except Exception as exc:
            log.warning("  skip lang_id=%d: %s", lang_id, exc)
            continue

        rows: list[tuple] = []
        for chapter_str, chapter_verses in data.items():
            chapter_id = int(chapter_str)
            for verse_str, verse_payload in chapter_verses.items():
                verse_num = int(verse_str)
                translations: list[str] = (
                    verse_payload[0] if verse_payload else []
                )
                for pos, text in enumerate(translations, start=1):
                    rows.append((chapter_id, verse_num, pos, lang_id, text or ""))

        if not rows:
            log.warning("  no data for lang_id=%d, skipping", lang_id)
            continue

        log.info("  inserting %d word translations for lang_id=%d …", len(rows), lang_id)
        await conn.copy_records_to_table(
            "word_translations",
            records=rows,
            columns=["chapter_id", "verse_num", "word_position",
                     "language_id", "translation"],
        )
        log.info("  → done lang_id=%d", lang_id)


async def seed_verse_translations(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
) -> None:
    """Fetch and insert full-verse translations for every resource."""
    for resource_id, version in VERSE_TRANSLATION_RESOURCES.items():
        url = f"{CDN}/verse-translations/{resource_id}.json?version={version}"
        log.info("Fetching verse translations resource_id=%d …", resource_id)
        try:
            raw: Any = await fetch_json(session, url)
        except Exception as exc:
            log.warning("  skip resource_id=%d: %s", resource_id, exc)
            continue

        normalised = normalise_verse_translation(raw)
        if not normalised:
            log.warning("  no data for resource_id=%d, skipping", resource_id)
            continue

        rows = [
            (chapter_id, verse_num, resource_id, text)
            for (chapter_id, verse_num), text in normalised.items()
            if text
        ]

        log.info(
            "  inserting %d verse translations for resource_id=%d …",
            len(rows),
            resource_id,
        )
        await conn.copy_records_to_table(
            "verse_translations",
            records=rows,
            columns=["chapter_id", "verse_num", "resource_id", "translation"],
        )
        log.info("  → done resource_id=%d", resource_id)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
async def main(dsn: str) -> None:
    connector = aiohttp.TCPConnector(limit=8)
    timeout = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        log.info("Connecting to PostgreSQL …")
        conn: asyncpg.Connection = await asyncpg.connect(dsn)
        try:
            await seed_chapters(conn)
            await seed_verses_and_words(conn, session)
            await seed_word_translations(conn, session)
            await seed_verse_translations(conn, session)
            log.info("✓ Seeding complete")
        finally:
            await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the Quran WBW PostgreSQL database from the quranwbw CDN"
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL"),
        help=(
            "asyncpg-compatible DSN, e.g. "
            "postgresql://user:password@localhost:5432/quran  "
            "(defaults to DATABASE_URL env var)"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.dsn:
        log.error(
            "No DSN provided.  Use --dsn or set the DATABASE_URL environment variable."
        )
        sys.exit(1)
    asyncio.run(main(args.dsn))
