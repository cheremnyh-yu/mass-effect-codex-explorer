# -*- coding: utf-8 -*-
"""Parse data/raw/andromeda_codex.pdf into a clean, structured entry
list matching the same {text, entities} shape as codex_clean.json/
timeline_clean.json, so all three corpora can share one entity graph.

Structure of the source PDF (confirmed by inspection): a table of contents
lists every entry title, in document order, as "Title .......... N" (dot
leader + page number). Unlike the docx codex, titles in the body have NO
trailing colon and aren't reliably separated from the preceding paragraph by
a blank line (sub-headings like "Know Associates" sometimes glue directly
onto the prior sentence with a single newline) -- so titles can't be detected
from body formatting alone. Instead, each TOC title is located by sequential
text search directly in the flattened body text (all 190 titles were found
this way with zero misses), and body content is whatever falls between one
title's position and the next.

Title shape is otherwise the same "Name" (primary) / "Category: Name"
(secondary) split as the docx codex, so entry-id/category logic is mirrored
from build_codex.py.

Output: data/processed/andromeda_clean.json -- a JSON array of
    {entry_id, entry_name, category, is_primary, text, entities}
records, one per atomic sentence, grouped by entry in document order.
"""
import json
import re
from pathlib import Path

from pypdf import PdfReader

from entity_lib import (
    ENTITY_ALIASES, DROP_ENTITIES, STRIP_LEADING, WHITELIST, slugify,
    extract_entities, split_sentences, finalize_entities, propagate_pronoun_subject,
)

ROOT = Path(__file__).parent.parent
RAW = ROOT.parent / "mass-effect-codex-raw"
PROCESSED = ROOT / "data" / "processed"

SRC = RAW / "andromeda_codex.pdf"
OUT = PROCESSED / "andromeda_clean.json"
TIMELINE = PROCESSED / "timeline_clean.json"
CODEX = PROCESSED / "codex_clean.json"

TITLE_RE = re.compile(r"^(.{2,99})$")
CONNECTOR_WORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "at", "as", "to",
                   "for", "with", "from", "&"}

HEADER_FOOTER_RE = re.compile(r"MEL \(Mass Effect Lore\)[^\n]*")
TOC_LINE_RE = re.compile(r"^(.*?)\s*\.{3,}\s*\d+\s*$")


def is_title_case(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", text)
    if not words:
        return False
    for w in words:
        if w.lower() in CONNECTOR_WORDS:
            continue
        if not w[0].isupper():
            return False
    return True


def strip_parenthetical(name: str) -> str:
    n = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    n = re.sub(r'"[^"]*"', " ", n)
    return re.sub(r"\s+", " ", n).strip()


def clean_name_words(name: str):
    words = name.split()
    while words and words[0].rstrip(".") in STRIP_LEADING and len(words) > 1:
        words = words[1:]
    return words


def load_known_slugs():
    known = set(WHITELIST.keys()) | set(ENTITY_ALIASES.values())
    for path in (TIMELINE, CODEX):
        if path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
            for e in events:
                known.update(e["entities"])
    return known


# pure organizational folders, not a real semantic parent
GROUPING_CATEGORIES = {"Planets", "Planet", "Region", "Stations", "Uncharted Worlds"}
# purely descriptive facets of whatever they're filed under, not a distinct
# named thing -- same "FTL Drive: Appearance" fold rule as the main codex
GENERIC_SUBTOPIC_SLUGS = {
    "History", "Culture", "Culture_and_Society", "Biology", "Government",
    "Religion", "Military_Doctrine", "Economy", "Economics", "Technology",
    "Spirituality", "Languages", "Law_and_Politics",
}


def new_entry(title_text, known_slugs):
    inner = title_text.strip()
    if ": " in inner:
        category_raw, name_raw = inner.split(": ", 1)
    else:
        category_raw = name_raw = inner

    display_name = strip_parenthetical(name_raw)
    name_words = clean_name_words(display_name)
    bare_slug = slugify(" ".join(name_words))
    # e.g. "Humans: Systems Alliance" -> bare_slug "Systems_Alliance" is itself
    # an ENTITY_ALIASES key pointing at the already-established
    # Earth_Systems_Alliance -- check the alias-resolved form against
    # known_slugs, not just the raw bare_slug, or this never matches
    resolved_bare = ENTITY_ALIASES.get(bare_slug, bare_slug)

    cat_words = clean_name_words(strip_parenthetical(category_raw))
    cat_slug = slugify(" ".join(cat_words))
    cat_slug = ENTITY_ALIASES.get(cat_slug, cat_slug)

    # computed up front, independent of which entry_id branch fires below --
    # a genuine "Category: Name" split still means the category, even when
    # the bare name happens to already be a known entity elsewhere (e.g. once
    # "Technology_Terraforming" is aliased to bare "Terraforming", that bare
    # name becomes a known_slug and would otherwise short-circuit into the
    # "already established" branch below, which never sets category_entity --
    # silently dropping the Technology link on the very next rebuild)
    is_grouping = category_raw.strip() in GROUPING_CATEGORIES
    category_entity = None
    if not is_grouping and category_raw != name_raw and len(cat_slug) >= 2 and cat_slug != bare_slug:
        category_entity = cat_slug

    if resolved_bare in known_slugs or category_raw == name_raw or is_grouping:
        entry_id = resolved_bare
    elif bare_slug in GENERIC_SUBTOPIC_SLUGS:
        # only fold when the sub-entry is a generic descriptive facet
        # (Biology, Culture, History...) of its species/category -- NOT every
        # "Species: X" sub-entry, since several (e.g. "Krogan: Overlord Nakmor
        # Morda", "Angara: Evfra de Tershaa", "Kett: The Archon") name a
        # distinct character/faction that deserves its own node, not to be
        # silently absorbed into the species hub
        entry_id = cat_slug
        category_entity = None  # folds straight into the category itself
    else:
        entry_id = f"{cat_slug}_{bare_slug}"

    entry_id = ENTITY_ALIASES.get(entry_id, entry_id)
    is_primary = category_raw == name_raw
    return entry_id, " ".join(name_words), category_raw.strip(), category_entity, is_primary


def load_titles_and_body():
    reader = PdfReader(SRC)
    full = "\n".join(page.extract_text() for page in reader.pages)

    toc_start = full.find("TABLE OF CONTENT")
    body_start = full.find("The Andromeda Initiative", toc_start + 2000)
    toc_raw = full[toc_start:body_start]

    titles = []
    for line in toc_raw.split("\n"):
        line = line.strip()
        if not line or line == "TABLE OF CONTENT" or "MEL (Mass Effect Lore)" in line:
            continue
        m = TOC_LINE_RE.match(line)
        if m:
            titles.append(m.group(1).strip())

    body = full[body_start:]
    body = HEADER_FOOTER_RE.sub(" ", body)
    # PDF line-wrap glitch: "Alliance" gets split with a stray space in the
    # middle ("Alli ance") in Sloane Kelly's bio, fragmenting it into a bogus
    # "Alli" entity instead of matching the Earth_Systems_Alliance whitelist
    body = body.replace("Alli ance", "Alliance")
    # mark original blank-line paragraph boundaries with a sentinel BEFORE
    # collapsing whitespace, so a title's own words appearing mid-sentence
    # inside some OTHER entry's prose (e.g. "...encouraged to write this
    # entry by Alec Ryder." inside SAM's bio) can't be mistaken for the real
    # "Alec Ryder" title -- only a match sitting at a genuine paragraph edge
    # (right after/before a sentinel) is trusted
    body = re.sub(r"\n *\n", "\x00", body)
    body = re.sub(r"\s+", " ", body).strip()
    return titles, body


BOUNDARY = "\x00"


def find_title_at_boundary(body, title, start):
    """Like body.find(title, start), but only accepts a match that sits at a
    genuine paragraph edge (BOUNDARY before or after it, skipping over any
    plain spaces left between the match and the sentinel) -- skips over
    false-positive matches where the title's own text is merely quoted/
    mentioned inside a different entry's running prose."""
    pos = start
    while True:
        idx = body.find(title, pos)
        if idx == -1:
            return -1
        b = idx - 1
        while b >= 0 and body[b] == " ":
            b -= 1
        before_ok = b < 0 or body[b] == BOUNDARY
        e = idx + len(title)
        while e < len(body) and body[e] == " ":
            e += 1
        after_ok = e >= len(body) or body[e] == BOUNDARY
        if before_ok or after_ok:
            return idx
        pos = idx + 1


def main():
    known_slugs = load_known_slugs()
    titles, body = load_titles_and_body()

    # locate every TOC title in sequence; content between one title's end and
    # the next title's start is that entry's raw (unsplit) body text
    spans = []  # (title, start_of_title_text, end_of_title_text)
    pos = 0
    for t in titles:
        idx = find_title_at_boundary(body, t, pos)
        if idx == -1:
            print(f"WARNING: title not found in sequence, skipping: {t!r}")
            continue
        spans.append((t, idx, idx + len(t)))
        pos = idx + len(t)

    entries = {}
    order = []
    occurrence_log = {}

    for i, (title, _, text_end) in enumerate(spans):
        chunk_end = spans[i + 1][1] if i + 1 < len(spans) else len(body)
        raw_body = body[text_end:chunk_end].replace(BOUNDARY, " ")
        raw_body = re.sub(r"\s+", " ", raw_body).strip()

        entry_id, name, category, category_entity, is_primary = new_entry(title, known_slugs)
        if entry_id not in entries:
            entries[entry_id] = {
                "entry_id": entry_id, "entry_name": name, "category": category,
                "category_entity": category_entity,
                "is_primary": is_primary, "body": [],
            }
            order.append(entry_id)
        if raw_body:
            entries[entry_id]["body"].append(raw_body)

    records = []
    injected_category_entities = set()
    for entry_id in order:
        e = entries[entry_id]
        pending = []
        for line in e["body"]:
            for sent in split_sentences(line):
                found = extract_entities(sent, occurrence_log)
                found[entry_id] = e["entry_name"]
                if e["category_entity"]:
                    found[e["category_entity"]] = e["category_entity"]
                    injected_category_entities.add(e["category_entity"])
                pending.append((sent, found))

        propagate_pronoun_subject(pending)
        for sent, found in pending:
            records.append({
                "entry_id": entry_id,
                "entry_name": e["entry_name"],
                "category": e["category"],
                "is_primary": e["is_primary"],
                "text": sent,
                "entities": found,
            })

    dropped = finalize_entities(records, occurrence_log, always_confirmed=injected_category_entities)
    for r in records:
        canonical_id = ENTITY_ALIASES.get(r["entry_id"], r["entry_id"])
        if canonical_id not in r["entities"] and canonical_id not in DROP_ENTITIES:
            r["entities"] = sorted(set(r["entities"]) | {canonical_id})

    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(entries)} Andromeda codex entries, {len(records)} sentence records -> {OUT}")
    print(f"Dropped {dropped} sentence-initial-only single-word false positives")


if __name__ == "__main__":
    main()
