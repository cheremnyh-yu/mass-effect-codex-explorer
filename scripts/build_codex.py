import json
import re
from pathlib import Path

import docx

from entity_lib import (
    ENTITY_ALIASES, DROP_ENTITIES, STRIP_LEADING, WHITELIST, slugify,
    extract_entities, split_sentences, finalize_entities, propagate_pronoun_subject,
)

ROOT = Path(__file__).parent.parent
RAW = ROOT.parent / "mass-effect-codex-raw"
PROCESSED = ROOT / "data" / "processed"

SRC = RAW / "mass_effect_codex.docx"
OUT = PROCESSED / "codex_clean.json"
TIMELINE = PROCESSED / "timeline_clean.json"

TITLE_RE = re.compile(r"^(.{2,99}):\s*$")
CONNECTOR_WORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "at", "as", "to",
                   "for", "with", "from", "&"}


def is_title_case(text: str) -> bool:
    """True if every content word is capitalized (allows lowercase connectors) --
    distinguishes real entry titles ("Military Doctrine") from body sentences that
    just happen to end in a colon ("C-Sec has six divisions:")."""
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
    """Entities already established by the timeline pipeline -- if a secondary
    entry's bare sub-topic name (e.g. "Genophage", "Migrant Fleet") already
    matches one of these, keep it bare; otherwise prefix with its category so
    generic sub-topics ("Biology", "Culture", "Government"...) don't collide
    across species (Asari: Biology vs. Turian: Biology are different entries)."""
    known = set(WHITELIST.keys()) | set(ENTITY_ALIASES.values())
    if TIMELINE.exists():
        events = json.loads(TIMELINE.read_text(encoding="utf-8"))
        for e in events:
            known.update(e["entities"])
    return known


def main():
    known_slugs = load_known_slugs()
    d = docx.Document(SRC)
    paras = [(p.style.name if p.style else "", p.text.strip()) for p in d.paragraphs]
    paras = [(s, t) for s, t in paras if t]
    # docx typo: "lllusive" (three lowercase L's) instead of "Illusive" -- breaks
    # the capitalized-proper-noun scan so "the lllusive Man" fragments into a
    # bare, generic "Man" instead of tagging Illusive_Man
    paras = [(s, t.replace("lllusive", "Illusive")) for s, t in paras]

    # skip front matter/TOC: real entries start at the first section divider
    start = 0
    for i, (style, text) in enumerate(paras):
        if "berschrift" in style and "Primary Codex Entries" in text:
            start = i
            break
    paras = paras[start:]

    entries = {}  # canonical entry_id -> dict
    order = []
    current = None
    occurrence_log = {}
    dropped_list_intros = []

    # pure organizational folders in the docx, not a real semantic parent the way
    # "Turian: Government" makes Government a sub-topic OF turians -- "Planets:
    # Feros" is just Feros filed under a "Planets" heading, so the entry IS Feros,
    # not a "Planets" sub-topic that needs disambiguating from other planets
    GROUPING_CATEGORIES = {"Planets", "Planet", "Region", "Stations",
                            "Non-Council Races", "Uncharted Worlds", "Citadel Station",
                            "Normandy Armor Upgrade", "Normandy Shield Upgrade",
                            "Normandy Weapon Upgrade"}
    # species/race sub-topics (Biology, Culture, Government, Military Doctrine,
    # Religion...) fold straight into the race's own node instead of forking a
    # separate "Asari_Biology" entity -- one hub per race, not one per sub-topic
    SPECIES_CATEGORIES = {
        "Asari", "Salarian", "Salarians", "Turian", "Turians", "Krogan",
        "Quarian", "Quarians", "Geth", "Batarian", "Batarians", "Volus",
        "Elcor", "Hanar", "Drell", "Vorcha", "Yahg", "Rachni", "Prothean",
        "Protheans", "Human", "Humans", "Angara", "Kett", "Raloi", "Leviathan",
        "Reaper", "Reapers", "Collector", "Collectors",
    }
    # sub-entry names that are purely descriptive facets of whatever they're filed
    # under (how it looks, how it's charged, how it's trained) rather than a
    # distinct named thing in its own right -- unlike "Cerberus: Phantom" (a
    # distinct trooper type) or "Starships: Frigates" (a distinct ship class),
    # these fold into their parent's own node instead of forking e.g. a separate
    # "FTL_Drive_Appearance" node for what is still just the FTL Drive
    GENERIC_SUBTOPIC_SLUGS = {
        "Appearance", "Drive_Charge", "Combat_Endurance", "Planetary_Assaults",
        "Pursuit_Tactics", "Trans_Relay_Assaults", "Crew_Considerations",
        "Heat_Management", "Sensors", "Thrusters", "Training", "Life_as_a_Biotic",
        "Administration", "Methodology", "Translation", "Prefabricated_Structures",
        "Geological_Survey", "Military_Jargon", "Military_Ranks", "Military_Doctrine",
    }

    def new_entry(title_text):
        m = TITLE_RE.match(title_text)
        inner = m.group(1)
        if ": " in inner:
            category_raw, name_raw = inner.split(": ", 1)
        else:
            category_raw = name_raw = inner

        display_name = strip_parenthetical(name_raw)
        name_words = clean_name_words(display_name)
        bare_slug = slugify(" ".join(name_words))

        cat_words = clean_name_words(strip_parenthetical(category_raw))
        cat_slug = slugify(" ".join(cat_words))
        cat_slug = ENTITY_ALIASES.get(cat_slug, cat_slug)

        # the category is only a *separate* real entity worth tagging when it's
        # neither a pure organizational label (GROUPING_CATEGORIES) nor already
        # folded into entry_id itself (species sub-topics) -- e.g. "Systems
        # Alliance: Military Doctrine:" should also tag Earth_Systems_Alliance
        # on every sentence, not just encode it in the name. This is computed
        # up front, independent of which entry_id branch fires below: a
        # genuine "Category: Name" split still means the category, even when
        # the bare name happens to already be a known entity elsewhere (e.g.
        # "Computers: Haptic Adaptive Interface" once "Haptic_Adaptive_
        # Interface" is itself aliased/known) -- if that check were inside
        # the entry_id branching, aliasing a compound entry to its bare name
        # would silently stop tagging its own category on the next rebuild,
        # since the bare name becomes a known_slug and short-circuits into
        # the "already established" branch that never sets category_entity
        is_grouping = category_raw.strip() in GROUPING_CATEGORIES
        category_entity = None
        if (not is_grouping and category_raw != name_raw and len(cat_slug) >= 2
                and cat_slug != bare_slug):
            category_entity = cat_slug

        if bare_slug in known_slugs or category_raw == name_raw or is_grouping:
            entry_id = bare_slug
        elif category_raw.strip() in SPECIES_CATEGORIES or bare_slug in GENERIC_SUBTOPIC_SLUGS:
            entry_id = cat_slug
            category_entity = None  # folds straight into the category itself --
            # a separate self-tag would just duplicate entry_id's own tag
        else:
            entry_id = f"{cat_slug}_{bare_slug}"

        entry_id = ENTITY_ALIASES.get(entry_id, entry_id)
        # true "is this a bare title with no Category: Name split" check, on the
        # raw strings before cleanup -- comparing the cleaned name against the
        # uncleaned category (as the old call-site check did) falsely says
        # False for "The Asari:" since "The" survives in category but not name
        is_primary = category_raw == name_raw
        return entry_id, " ".join(name_words), category_raw.strip(), category_entity, is_primary

    # "Further Codex Entries" is a nav label and "Personal History Summary" is a
    # bare (colon-less) chapter header for the Spacer/Colonist/Earthborn section
    # that follows -- neither is real prose, but with no trailing colon they slip
    # past title detection and glue onto whatever entry precedes them (Upgrades)
    SECTION_DIVIDERS = {"Primary Codex Entries", "Secondary Codex Entries",
                         "Further Codex Entries", "Personal History Summary"}
    # in-entry subsection markers ("here's what's new for this topic in ME2") --
    # fourth-wall game references, not real entries; their body should stay
    # attached to whatever entry they're a subsection of, not fork into their own
    GAME_SUBHEADINGS = {
        "Mass Effect", "Mass Effect 2", "Mass Effect 3", "Mass Effect Andromeda",
        "Mass Effect Galaxy", "Mass Effect and Mass Effect 2",
    }
    STRAY_NUMBERING_RE = re.compile(r"^\d+(?:\.\d+)+\s+")  # one title has a literal
    # "8.2.5 " outline-number prefix baked into the paragraph text itself
    BARE_SUBHEADING_IDS = {"Paragon", "Renegade"}  # written as their own bare
    # paragraph ("Paragon:") right after the topic they belong to, never as a
    # single "Battle of the Citadel: Paragon:" title -- so the bracket label
    # needs to borrow the preceding real heading as their category by hand
    last_real_title = None
    for style, text in paras:
        text = STRAY_NUMBERING_RE.sub("", text)
        if text == "Pratoerians:":
            # docx typo: the entry title transposes two letters, but the body
            # text itself spells it correctly ("praetorians are well-armored
            # killing machines...") -- normalize so the entry_id matches
            text = "Praetorians:"
        if text == "Planets: Ilos":
            # one-off docx typo: every sibling in this list ("Planets: Feros :",
            # "Planets: Noveria:", "Planets: Virmire:") has a trailing colon:
            # this one doesn't, so it fails title detection and Ilos's real body
            # silently glues onto the preceding Feros entry as bogus extra text
            text = "Planets: Ilos:"
        if text in SECTION_DIVIDERS or text.rstrip(":") in GAME_SUBHEADINGS:
            continue
        # Note: entry titles later in the doc (companion bios, the Spacer/Colonist/
        # Earthborn background blurbs, several one-off tech/planet entries) use the
        # "Uberschrift" paragraph style, same as the two section dividers above --
        # so titling can't be gated on style, only on the colon+title-case shape.
        m = TITLE_RE.match(text)
        if m and len(text) < 100 and is_title_case(m.group(1)):
            entry_id, name, category, category_entity, is_primary = new_entry(text)
            if entry_id in BARE_SUBHEADING_IDS and last_real_title:
                category, is_primary = last_real_title, False
            elif entry_id not in BARE_SUBHEADING_IDS:
                last_real_title = name
            # DROP_ENTITIES means "never a tag/node" (handled by finalize_entities
            # and the self-tag check below), not "discard the body" -- Paragon:/
            # Renegade: sub-headings under a topic (e.g. "Rise of the Alliance:")
            # often carry real, *divergent* lore (different political outcomes per
            # playthrough), not just redundant retellings; only "Timeline" (the
            # docx's own condensed recap, already covered by timeline_clean.json)
            # is worth skipping outright
            if entry_id == "Timeline":
                current = None
                continue
            if entry_id not in entries:
                entries[entry_id] = {
                    "entry_id": entry_id, "entry_name": name, "category": category,
                    "category_entity": category_entity,
                    "is_primary": is_primary, "body": [],
                }
                order.append(entry_id)
            current = entries[entry_id]
            continue
        if text.endswith(":") and len(text.split()) <= 15:
            # a colon-ending line that failed the title-case check -- likely a
            # list-intro sentence ("C-Sec has six divisions:"); keep as body
            # prose, not a title
            dropped_list_intros.append(text)
        if current is not None:
            current["body"].append(text)

    records = []
    injected_category_entities = set()
    for entry_id in order:
        e = entries[entry_id]
        pending = []  # (sent, found) for the whole entry, before pronoun carry-forward
        for line in e["body"]:
            for sent in split_sentences(line):
                found = extract_entities(sent, occurrence_log)
                found[entry_id] = e["entry_name"]  # always self-tag the entry's own hub
                if e["category_entity"]:  # e.g. tag Earth_Systems_Alliance on every
                    found[e["category_entity"]] = e["category_entity"]  # "Military Doctrine" sentence
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

    # exact-duplicate sentence text shows up two ways: (1) narrative-choice
    # families (Spacer/Colonist/Earthborn x Sole Survivor/War Hero/Ruthless,
    # Anderson/Udina as councilor, Paragon/Renegade, the Geth/Quarian ending)
    # repeat the SAME sentence verbatim across DROP_ENTITIES siblings; (2) a
    # handful of real entries (e.g. "Reapers: Indoctrination:" and the later
    # standalone "Indoctrination:") restate the same descriptive block under
    # two different headings. Either way keeping every copy inflates
    # co-occurrence weight for whatever the sentence mentions, so collapse
    # exact duplicates to one record, merging in every copy's own entity tags
    # (not just dropping) so a real entry's self-tag is never lost in the merge
    first_by_text = {}
    deduped_records = []
    merged_entry_ids = {}  # id(record) -> set of every entry_id folded into it
    for r in records:
        prev = first_by_text.get(r["text"])
        if prev is not None:
            prev["entities"].update(r["entities"])
            merged_entry_ids.setdefault(id(prev), {prev["entry_id"]}).add(r["entry_id"])
            continue
        first_by_text[r["text"]] = r
        deduped_records.append(r)
    dropped_dupes = len(records) - len(deduped_records)
    records = deduped_records

    dropped = finalize_entities(records, occurrence_log, always_confirmed=injected_category_entities)
    for r in records:
        # a merged (deduplicated) record must keep re-tagging EVERY entry_id that
        # contributed to it (e.g. both Reaper and Indoctrination), not just its
        # own -- otherwise the single-word confirmation filter above silently
        # drops whichever entry's self-tag isn't r["entry_id"] itself
        for entry_id in merged_entry_ids.get(id(r), (r["entry_id"],)):
            canonical_id = ENTITY_ALIASES.get(entry_id, entry_id)
            if canonical_id not in r["entities"] and canonical_id not in DROP_ENTITIES:
                r["entities"] = sorted(set(r["entities"]) | {canonical_id})

    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(entries)} codex entries, {len(records)} sentence records -> {OUT}")
    print(f"Dropped {dropped_dupes} duplicate-text sentences repeated across narrative-choice siblings")
    print(f"Dropped {dropped} sentence-initial-only single-word false positives")
    print(f"{len(dropped_list_intros)} colon-ending body lines treated as prose, not titles:")
    for t in dropped_list_intros:
        print(f"   - {t}")


if __name__ == "__main__":
    main()
