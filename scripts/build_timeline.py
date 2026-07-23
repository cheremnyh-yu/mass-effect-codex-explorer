# -*- coding: utf-8 -*-
"""Parse data/raw/timeline_raw.txt (raw fandom-wiki timeline dump) into a clean,
structured event list for the entity-embedding / Neural CDE pipeline.

Output: data/processed/timeline_clean.json -- a JSON array of
    {year, year_end, approx, era, title, text, entities}
records, one per atomic sentence/event, in chronological source order.
"""
import json
import re
from pathlib import Path

from entity_lib import extract_entities, split_sentences, finalize_entities, propagate_pronoun_subject

ROOT = Path(__file__).parent.parent
SRC = ROOT.parent / "mass-effect-codex-raw" / "timeline_raw.txt"
OUT = ROOT / "data" / "processed" / "timeline_clean.json"

DATE_RE = re.compile(
    r"^(?P<approx>c\.\s*)?"
    r"(?P<y1>Unknown|[\d,]+)"
    r"(?:\s*[-–]\s*(?:c\.\s*)?(?P<y2>[\d,]+))?"
    r"(?P<decade>s)?\s*"
    r"(?P<era_suffix>BCE|CE)"
    r"(?:\s*:\s*(?P<title>.+))?$"
)

ERA_RE = re.compile(r"^(?P<name>[A-Za-z][\w /,\-]+?)\s*\([^)]*(?:BCE|CE)[^)]*\)$")

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
MONTH_DAY_RE = re.compile(rf"^({'|'.join(MONTHS)})\s+\d{{1,2}}:\s*(.*)$")

# "The events of Mass Effect: X occur/begin/continue." is a meta/fourth-wall marker
# citing which game or comic a story beat comes from -- not an in-universe event itself.
META_EVENT_RE = re.compile(r"^The events of .+ (?:occur|begin|continue)\.?$", re.IGNORECASE)


def parse_year(m):
    approx = bool(m.group("approx")) or bool(m.group("decade"))
    y1_raw = m.group("y1")
    era_suffix = m.group("era_suffix")
    if y1_raw == "Unknown":
        return None, None, True
    y1 = int(y1_raw.replace(",", ""))
    if era_suffix == "BCE":
        y1 = -y1
    y2 = None
    if m.group("y2"):
        y2 = int(m.group("y2").replace(",", ""))
        if era_suffix == "BCE":
            y2 = -y2
    return y1, y2, approx


def main():
    text = SRC.read_text(encoding="utf-8")
    # fix two known glued caption/sentence lines (no space where the source concatenated them)
    text = text.replace("near LunaThe Andromeda", "near Luna. The Andromeda")
    text = text.replace("for the first timeArk Leusinia", "for the first time. Ark Leusinia")

    lines = [l.rstrip("\n") for l in text.split("\n")]

    # skip preamble/TOC: real content starts right after the first "Advertisement" marker
    start = 0
    for i, l in enumerate(lines):
        if l.strip() == "Advertisement":
            start = i + 1
            break
    lines = lines[start:]

    era = None
    date_info = None  # (year, year_end, approx, title)
    body_lines = []
    records = []
    dropped_captions = []
    dropped_meta_events = []
    occurrence_log = {}  # slug -> {"initial": bool, "noninitial": bool}, single-word only

    def flush():
        if date_info is None:
            return
        year, year_end, approx, title = date_info
        block_lines = list(body_lines)
        # drop a leading image-caption fragment: no terminal punctuation, short,
        # AND only when some other line in the block is real punctuated prose
        # (a block made entirely of terse dash-fact lines is not a caption+paragraph pair)
        if len(block_lines) > 1:
            first = block_lines[0]
            rest_has_prose = any(re.search(r"[.!?]$", l) for l in block_lines[1:])
            if not re.search(r"[.!?]$", first) and len(first.split()) <= 10 and rest_has_prose:
                dropped_captions.append(first)
                block_lines = block_lines[1:]
        if not block_lines:
            return
        # split per source line first (each line is already one fact in this source),
        # then split further on sentence punctuation within a line
        pending = []  # (month_day, sent, found), pronoun carry-forward applied per line
        for line in block_lines:
            month_day = None
            md_m = MONTH_DAY_RE.match(line)
            if md_m:
                month_day = f"{md_m.group(1)} {line.split()[1].rstrip(':')}"
                line = md_m.group(2)
            line_pending = []
            for sent in split_sentences(line):
                if META_EVENT_RE.match(sent):
                    dropped_meta_events.append(sent)
                    continue
                found = extract_entities(sent, occurrence_log)
                line_pending.append((sent, found))
            # scoped to this one original paragraph line -- a date block can bundle
            # several unrelated facts together, and a subject from an earlier,
            # unrelated line must not leak into this line's pronoun sentences
            propagate_pronoun_subject(line_pending)
            pending.extend((month_day, sent, found) for sent, found in line_pending)

        for month_day, sent, found in pending:
            records.append({
                "year": year,
                "year_end": year_end,
                "approx": approx,
                "era": era,
                "title": title,
                "date_detail": month_day,
                "text": sent,
                "entities": found,  # slug -> display name, filtered below
            })

    for line in lines:
        s = line.strip()
        if not s or s == "Advertisement":
            continue
        era_m = ERA_RE.match(s)
        if era_m and not DATE_RE.match(s):
            flush()
            date_info = None
            body_lines = []
            era = era_m.group("name").strip()
            continue
        date_m = DATE_RE.match(s)
        if date_m:
            flush()
            y1, y2, approx = parse_year(date_m)
            date_info = (y1, y2, approx, date_m.group("title"))
            body_lines = []
            continue
        body_lines.append(s)
    flush()

    dropped_entity_mentions = finalize_entities(records, occurrence_log)

    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Parsed {len(records)} timeline records -> {OUT}")
    print(f"Dropped {len(dropped_captions)} caption-like lines:")
    for c in dropped_captions:
        print(f"   - {c}")
    print(f"Dropped {dropped_entity_mentions} sentence-initial-only single-word false-positive entity mentions")
    print(f"Dropped {len(dropped_meta_events)} fourth-wall 'events of X occur/begin/continue' meta-markers:")
    for m in dropped_meta_events:
        print(f"   - {m}")


if __name__ == "__main__":
    main()
