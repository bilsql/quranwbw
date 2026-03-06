-- =============================================================================
-- Quran Word-by-Word – PostgreSQL Schema
-- Compatible with PostgreSQL 18+ and the asyncpg Python driver
--
-- Data source: https://static.quranwbw.com/data/v4  (quranwbw CDN)
--
-- Layout
-- ──────
-- chapters                    114 Quranic chapters (surahs)
-- verses                      6 236 verses (ayahs) with mushaf metadata
-- words                       Word-by-word Arabic text (Uthmanic script)
-- word_translation_languages  Lookup table – one row per word-translation language
-- word_translations           Translation of every individual Arabic word
-- verse_translation_resources Lookup table – one row per verse-translation resource
-- verse_translations          Full ayah translations (many translators / languages)
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1.  chapters
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chapters (
    id                  SMALLINT    PRIMARY KEY,          -- 1–114
    arabic              TEXT        NOT NULL,             -- Arabic name
    translation         TEXT        NOT NULL,             -- English meaning
    transliteration     TEXT        NOT NULL,             -- Latin transliteration
    verse_count         SMALLINT    NOT NULL,             -- number of verses
    revelation_type     SMALLINT    NOT NULL              -- 1 = Meccan, 2 = Medinan
);

-- ---------------------------------------------------------------------------
-- 2.  verses
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verses (
    chapter_id          SMALLINT    NOT NULL REFERENCES chapters(id),
    verse_num           SMALLINT    NOT NULL,
    page                SMALLINT,                         -- mushaf page (1-604)
    juz                 SMALLINT,                         -- juz number (1-30)
    word_count          SMALLINT    NOT NULL DEFAULT 0,
    PRIMARY KEY (chapter_id, verse_num)
);

CREATE INDEX IF NOT EXISTS verses_juz_idx  ON verses (juz);
CREATE INDEX IF NOT EXISTS verses_page_idx ON verses (page);

-- ---------------------------------------------------------------------------
-- 3.  words  (word-by-word Arabic text)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS words (
    chapter_id          SMALLINT    NOT NULL,
    verse_num           SMALLINT    NOT NULL,
    word_position       SMALLINT    NOT NULL,             -- 1-based index in verse
    arabic_text         TEXT        NOT NULL,             -- Uthmanic script glyph
    transliteration     TEXT,                             -- Latin transliteration
    line_num            SMALLINT,                         -- mushaf line number
    PRIMARY KEY (chapter_id, verse_num, word_position),
    FOREIGN KEY (chapter_id, verse_num)
        REFERENCES verses (chapter_id, verse_num)
);

CREATE INDEX IF NOT EXISTS words_chapter_idx ON words (chapter_id);

-- ---------------------------------------------------------------------------
-- 4.  word_translation_languages  (lookup)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS word_translation_languages (
    id                  SMALLINT    PRIMARY KEY,          -- matches CDN translation id
    language_name       TEXT        NOT NULL,
    is_rtl              BOOLEAN     NOT NULL DEFAULT FALSE,
    font_class          TEXT                              -- optional CSS class hint
);

-- Seed the lookup table with all languages available on the quranwbw CDN.
-- language ids match selectableWordTranslations in src/data/options.js
INSERT INTO word_translation_languages (id, language_name, is_rtl, font_class) VALUES
    (1,  'English',                         FALSE, NULL),
    (2,  'Urdu',                            TRUE,  'font-Urdu'),
    (3,  'Hindi',                           FALSE, NULL),
    (4,  'Indonesian',                      FALSE, NULL),
    (5,  'Bangla',                          FALSE, NULL),
    (6,  'Turkish',                         FALSE, NULL),
    (7,  'Tamil',                           FALSE, NULL),
    (8,  'German',                          FALSE, NULL),
    (11, 'French',                          FALSE, NULL),
    (12, 'Malayalam (Amani Thafseer)',       FALSE, NULL),
    (13, 'Malayalam (Quran Lalithasaram)',   FALSE, NULL),
    (14, 'Chinese (Traditional)',           FALSE, NULL),
    (15, 'Chinese (Zhuyin)',                FALSE, NULL),
    (16, 'Chinese (Simplified)',            FALSE, NULL),
    (17, 'Chinese (Pinyin)',                FALSE, NULL),
    (18, 'Divehi',                          TRUE,  NULL),
    (19, 'Persian',                         TRUE,  'font-Urdu'),
    (20, 'Sindhi',                          TRUE,  'font-Sindhi'),
    (21, 'Albanian',                        FALSE, NULL),
    (22, 'Sign Language',                   FALSE, NULL)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5.  word_translations  (per word × per language)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS word_translations (
    chapter_id          SMALLINT    NOT NULL,
    verse_num           SMALLINT    NOT NULL,
    word_position       SMALLINT    NOT NULL,
    language_id         SMALLINT    NOT NULL
        REFERENCES word_translation_languages (id),
    translation         TEXT        NOT NULL,
    PRIMARY KEY (chapter_id, verse_num, word_position, language_id),
    FOREIGN KEY (chapter_id, verse_num, word_position)
        REFERENCES words (chapter_id, verse_num, word_position)
);

CREATE INDEX IF NOT EXISTS word_translations_lang_idx
    ON word_translations (language_id);
CREATE INDEX IF NOT EXISTS word_translations_verse_idx
    ON word_translations (chapter_id, verse_num, language_id);

-- ---------------------------------------------------------------------------
-- 6.  verse_translation_resources  (lookup)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verse_translation_resources (
    id                  SMALLINT    PRIMARY KEY,          -- matches CDN resource_id
    language_id         SMALLINT    NOT NULL,             -- BCP-47-like numeric id
    resource_name       TEXT        NOT NULL,
    is_rtl              BOOLEAN     NOT NULL DEFAULT FALSE,
    font_class          TEXT
);

-- Seed with all resources from selectableVerseTranslations in src/data/options.js
INSERT INTO verse_translation_resources (id, language_id, resource_name, is_rtl, font_class) VALUES
    -- Albanian (language_id 187)
    (88,  187, 'Hasan Efendi Nahi',                                        FALSE, NULL),
    -- Bangla (language_id 20)
    (161, 20,  'Taisirul Quran',                                            FALSE, NULL),
    (163, 20,  'Sheikh Mujibur Rahman',                                     FALSE, NULL),
    (162, 20,  'Rawai Al-bayan',                                            FALSE, NULL),
    (213, 20,  'Dr. Abu Bakr Muhammad Zakaria',                             FALSE, NULL),
    -- Chinese (language_id 185)
    (56,  185, 'Chinese Translation (Simplified) - Ma Jain',                FALSE, NULL),
    (109, 185, 'Muhammad Makin',                                            FALSE, NULL),
    -- Divehi (language_id 34)
    (86,  34,  'Office of the president of Maldives',                       TRUE,  NULL),
    (840, 34,  'Abu Bakr Ibrahim Ali (Bakurube)',                            TRUE,  NULL),
    -- English (language_id 38)
    (131, 38,  'The Clear Quran (Mustafa Khattab)',                         FALSE, NULL),
    (20,  38,  'Saheeh International',                                      FALSE, NULL),
    (84,  38,  'Mufti Taqi Usmani',                                         FALSE, NULL),
    (85,  38,  'Abdel Haleem',                                              FALSE, NULL),
    (95,  38,  'Abul Alaa Maududi',                                         FALSE, NULL),
    (19,  38,  'Pickthall',                                                 FALSE, NULL),
    (22,  38,  'Yusuf Ali',                                                 FALSE, NULL),
    (203, 38,  'Hilali & Khan',                                             FALSE, NULL),
    -- French (language_id 49)
    (779, 49,  'Rashid Maash',                                              FALSE, NULL),
    (136, 49,  'Montada Islamic Foundation',                                FALSE, NULL),
    (31,  49,  'French Translation (Muhammad Hamidullah)',                  FALSE, NULL),
    -- German (language_id 33)
    (208, 33,  'Abu Reda Muhammad ibn Ahmad',                               FALSE, NULL),
    (27,  33,  'Frank Bubenheim and Nadeem',                                FALSE, NULL),
    -- Hindi (language_id 60)
    (122, 60,  'Maulana Azizul Haque al-Umari',                             FALSE, NULL),
    -- Indonesian (language_id 67)
    (134, 67,  'King Fahad Quran Complex',                                  FALSE, NULL),
    (33,  67,  'Indonesian Islamic affairs ministry',                       FALSE, NULL),
    (141, 67,  'The Sabiq company',                                         FALSE, NULL),
    -- Malayalam (language_id 106)
    (224, 106, 'Abdul-Hamid Haidar & Kanhi Muhammad',                       FALSE, NULL),
    (80,  106, 'Muhammad Karakunnu and Vanidas Elayavoor',                   FALSE, NULL),
    (37,  106, 'Abdul Hameed and Kunhi',                                    FALSE, NULL),
    -- Persian (language_id 43)
    (135, 43,  'IslamHouse.com',                                            TRUE,  'font-Urdu'),
    (29,  43,  'Hussein Taji Kal Dari',                                     TRUE,  'font-Urdu'),
    -- Russian (language_id 138)
    (79,  138, 'Abu Adel',                                                  FALSE, NULL),
    (78,  138, 'Ministry of Awqaf, Egypt',                                  FALSE, NULL),
    (45,  138, 'Russian Translation (Elmir Kuliev)',                        FALSE, NULL),
    -- Sindhi (language_id 142)
    (238, 142, 'Taj Mehmood Amroti',                                        TRUE,  'font-Sindhi'),
    -- Tamil (language_id 158)
    (229, 158, 'Sheikh Omar Sharif bin Abdul Salam',                        FALSE, NULL),
    (50,  158, 'Jan Trust Foundation',                                      FALSE, NULL),
    (133, 158, 'Abdul Hameed Baqavi',                                       FALSE, NULL),
    -- Transliteration (language_id 11115)
    (1,   11115, 'Transliteration (Simple Tajweed)',                        FALSE, NULL),
    (3,   11115, 'Transliteration (Syllables)',                             FALSE, 'font-serif'),
    (57,  11115, 'Transliteration (Normal)',                                FALSE, NULL),
    (4,   11115, 'Transliteration (Advanced Tajweed)',                      FALSE, 'font-serif'),
    -- Turkish (language_id 167)
    (210, 167, 'Dar Al-Salam Center',                                       FALSE, NULL),
    (77,  167, 'Turkish Translation (Diyanet)',                             FALSE, NULL),
    (52,  167, 'Elmalili Hamdi Yazir',                                      FALSE, NULL),
    (112, 167, 'Shaban Britch',                                             FALSE, NULL),
    (124, 167, 'Muslim Shahin',                                             FALSE, NULL),
    -- Urdu (language_id 174)
    (156, 174, 'Fe Zilal al-Quran',                                         TRUE,  'font-Urdu'),
    (97,  174, 'Tafheem Ul Quran - Abul Alaa Maududi',                      TRUE,  'font-Urdu'),
    (234, 174, 'Fatah Muhammad Jalandhari',                                 TRUE,  'font-Urdu'),
    (158, 174, 'Bayan al-Quran (Dr. Israr Ahmad)',                          TRUE,  'font-Urdu'),
    (151, 174, 'Shaykh al-Hind Mahmud al-Hasan',                           TRUE,  'font-Urdu'),
    (54,  174, 'Maulana Muhammad Junagarhi',                                TRUE,  'font-Urdu'),
    (819, 174, 'Maulana Wahiduddin Khan',                                   TRUE,  'font-Urdu'),
    (831, 174, 'Abul Alaa Maududi (Roman Urdu)',                            FALSE, NULL)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7.  verse_translations  (full-ayah translations)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verse_translations (
    chapter_id          SMALLINT    NOT NULL,
    verse_num           SMALLINT    NOT NULL,
    resource_id         SMALLINT    NOT NULL
        REFERENCES verse_translation_resources (id),
    translation         TEXT        NOT NULL,
    PRIMARY KEY (chapter_id, verse_num, resource_id),
    FOREIGN KEY (chapter_id, verse_num)
        REFERENCES verses (chapter_id, verse_num)
);

CREATE INDEX IF NOT EXISTS verse_translations_resource_idx
    ON verse_translations (resource_id);
CREATE INDEX IF NOT EXISTS verse_translations_chapter_idx
    ON verse_translations (chapter_id, resource_id);

COMMIT;
