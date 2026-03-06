# Quran WBW — PostgreSQL integration

This directory provides a **PostgreSQL 18+ schema** and an **async Python seeder**
that fetches every piece of Quran word-by-word data from the quranwbw CDN and
stores it in a relational database.  The database is designed to be consumed by
an **asyncpg**-based API that can serve word-by-word translations in any supported
language to a web or mobile front-end.

---

## Files

| File | Purpose |
|------|---------|
| `schema.sql` | DDL – creates all tables, indexes, and seeds lookup data |
| `seed.py` | Async Python script – fetches CDN JSON and populates the DB |
| `requirements.txt` | Python dependencies (`asyncpg`, `aiohttp`) |

---

## How the Quran data is organised in quranwbw

The quranwbw front-end does **not** bundle a local database.  All Quran content
lives as versioned JSON files on the CDN at:

```
https://static.quranwbw.com/data/v4/
```

### Arabic words (word-by-word)

```
/words-data/arabic/{fontId}.json?version={v}
```

Top-level structure:

```json
{
  "1": {                      ← chapter id
    "1": [                    ← verse number
      ["word1", "word2"],     ← Arabic glyphs (one per word)
      [1, 1],                 ← mushaf line numbers
      ["end-icon"]            ← optional end-of-verse icon glyph
    ]
  }
}
```

Font IDs available: `1` (Uthmanic Digital), `2` (Mushaf 1441H), `3` (Mushaf
Tajweed), `5` (Uthman Taha Digital), etc.  The seeder uses font-id `1`.

### Word translations

```
/words-data/translations/{languageId}.json?version={v}
```

Structure identical to Arabic words; the inner array contains translated strings
instead of glyphs.

Available language IDs:

| ID | Language |
|----|----------|
| 1 | English |
| 2 | Urdu |
| 3 | Hindi |
| 4 | Indonesian |
| 5 | Bangla |
| 6 | Turkish |
| 7 | Tamil |
| 8 | German |
| 11 | French |
| 12 | Malayalam (Amani Thafseer) |
| 13 | Malayalam (Quran Lalithasaram) |
| 14 | Chinese (Traditional) |
| 15 | Chinese (Zhuyin) |
| 16 | Chinese (Simplified) |
| 17 | Chinese (Pinyin) |
| 18 | Divehi |
| 19 | Persian |
| 20 | Sindhi |
| 21 | Albanian |
| 22 | Sign Language |

### Word transliterations

```
/words-data/transliterations/{id}.json?version={v}
```

Same structure; IDs 1–4 for Normal, Simple Tajweed, Advanced Tajweed, Syllables.

### Verse metadata

```
/meta/verseKeyData.json?version=2
```

```json
{
  "1:1": { "chapter": 1, "verse": 1, "page": 1, "juz": 1, "words": 7 }
}
```

### Full-verse (ayah) translations

```
/verse-translations/{resourceId}.json?version={v}
```

The CDN may return either a flat `{"chapter:verse": "text"}` or a nested
`{"chapter": {"verse": "text"}}` format; `seed.py` handles both.

Over 50 translation resources are available across 16 languages.

---

## Database schema

```
chapters
  id · arabic · translation · transliteration · verse_count · revelation_type

verses
  chapter_id · verse_num · page · juz · word_count

words
  chapter_id · verse_num · word_position · arabic_text · transliteration · line_num

word_translation_languages  (lookup)
  id · language_name · is_rtl · font_class

word_translations
  chapter_id · verse_num · word_position · language_id · translation

verse_translation_resources  (lookup)
  id · language_id · resource_name · is_rtl · font_class

verse_translations
  chapter_id · verse_num · resource_id · translation
```

### Key query patterns (asyncpg)

```python
# Fetch all Arabic words + English translation for chapter 1
rows = await conn.fetch("""
    SELECT w.verse_num, w.word_position, w.arabic_text,
           wt.translation AS english
    FROM   words w
    JOIN   word_translations wt
           ON  wt.chapter_id   = w.chapter_id
           AND wt.verse_num    = w.verse_num
           AND wt.word_position = w.word_position
           AND wt.language_id  = 1          -- 1 = English
    WHERE  w.chapter_id = 1
    ORDER  BY w.verse_num, w.word_position
""")

# Fetch full-verse translation for chapter 2 (Saheeh International, resource_id 20)
rows = await conn.fetch("""
    SELECT verse_num, translation
    FROM   verse_translations
    WHERE  chapter_id  = 2
      AND  resource_id = 20
    ORDER  BY verse_num
""")

# All supported word-translation languages
langs = await conn.fetch("SELECT * FROM word_translation_languages ORDER BY id")
```

---

## Setup

### 1 · Apply the schema

```bash
psql "$DATABASE_URL" -f database/schema.sql
```

### 2 · Install Python dependencies

```bash
pip install -r database/requirements.txt
```

### 3 · Run the seeder

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/quran"
python database/seed.py
# or
python database/seed.py --dsn "postgresql://user:password@localhost:5432/quran"
```

The seeder fetches data concurrently (max 8 connections to the CDN) and uses
PostgreSQL `COPY` for bulk inserts.  A full run downloads ~60 translation files
and inserts roughly **1.6 million rows** in `word_translations` alone
(≈78,000 Arabic words × 20 languages), plus ~6,200 rows in `verses`,
~78,000 in `words`, and up to ~330,000 in `verse_translations`.

> **Note** The seeder is idempotent for chapters/verses (uses `ON CONFLICT DO
> NOTHING`).  Words and translations use `COPY`, so run the seeder against an
> empty database or truncate those tables before re-seeding.

---

## asyncpg API integration tips

* Use a **connection pool** (`asyncpg.create_pool`) in your API process.
* Pass the user's language preference as a parameter to avoid SQL injection.
* The `language_id` for word translations and the `resource_id` for verse
  translations are stable across CDN versions.
* `is_rtl` and `font_class` columns in the lookup tables let the front-end
  render Arabic-script languages correctly without extra logic.
