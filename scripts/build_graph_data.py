# -*- coding: utf-8 -*-
"""Merge timeline_clean.json (dated events) and codex_clean.json (the docx
codex entries) into one compact JSON blob for the codex-explorer artifact:
an entity co-occurrence network spanning both corpora, plus the timeline
event list (unchanged) for the Timeline view.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PROCESSED = Path(__file__).parent.parent / "data" / "processed"

TIMELINE_SRC = PROCESSED / "timeline_clean.json"
CODEX_SRC = PROCESSED / "codex_clean.json"
ANDROMEDA_SRC = PROCESSED / "andromeda_clean.json"
SCRIPT_SRC = PROCESSED / "script_clean.json"
OUT = PROCESSED / "graph_data.json"

TOP_N_NODES = 250
MIN_EDGE_WEIGHT = 1
MAX_EXAMPLES_PER_NODE = None  # None = keep every mention, not just a sample

# category buckets -- curated by hand against the top entities in this corpus.
# Anything not listed here falls through to prefix-inheritance below (e.g.
# "Asari_Biology" inherits Species from "Asari") before landing in "Other".
SPECIES = {
    "Asari", "Salarian", "Turian", "Krogan", "Quarian", "Geth", "Batarian",
    "Volus", "Elcor", "Hanar", "Drell", "Vorcha", "Yahg", "Rachni", "Prothean",
    "Human", "Angara", "Kett", "Raloi", "Leviathan", "Reaper", "Reapers",
    "Collector", "Husk", "Thresher_Maw", "Arthenn", "Thoihan", "Inusannon",
    "Zeioph", "Kirik", "Jardaan", "Varren",
}
CONFLICT = {
    "Rachni_Wars", "Krogan_Rebellions", "Unification_War", "First_Contact_War",
    "Morning_War", "Eden_Prime_War", "Anhur_Rebellions", "Skyllian_Blitz",
    "Metacon_War", "Theshaca_Raids", "Battle", "Skyllian_Verge", "Fall_of_Earth",
    "Fall_of_Thessia", "Battle_of_Palaven", "Reaper_War", "Miracle_at_Palaven",
    "Fall_of_Taetrus", "Harvesting",
}
TECH = {
    "Element_Zero", "Helium_3", "Antimatter", "Red_Sand", "Genophage",
    "Biotic", "Biotics", "Mass_Relay", "Mass_Effect_Field", "FTL", "AI",
    "Relay_314", "Omega_4_Relay", "Mu_Relay", "Alpha_Relay", "Crucible",
    "Conduit", "Scourge", "Remnant", "Arca_Monolith", "Space_Combat",
    "Communications", "Computers", "Weapons", "Starships", "Vehicles",
    "Technology", "Omni_tool", "Medi_Gel", "Drones", "Mass_Accelerators",
    "Body_Armor", "Small_Arms", "GARDIAN", "Shroud", "Genetic_Engineering",
    "Tech_Armor_and_Fortification", "Silaris_Armor", "Cyclonic_Barrier_Technology",
    "Thanix_Magnetic_Hydrodynamic_Weapon", "UT_47_Kodiak", "Mako",
}
FACTION = {
    "Cerberus", "Earth_Systems_Alliance", "Citadel_Council", "Council",
    "Turian_Hierarchy", "Blue_Suns", "Shadow_Broker", "Spectres",
    "Migrant_Fleet", "Andromeda_Initiative", "Angaran_Resistance", "Hegemony",
    "Parliament", "Systems_Alliance_Parliament", "Salarian_Union",
    "Special_Tasks_Group", "Alliance_Navy", "Terra_Firma", "Eclipse",
    "Blood_Pack", "Conatix_Industries", "Delta_Squad", "Batarian_Hegemony",
    "BAaT", "Mercenaries", "Asari_Republics", "Alliance_News_Network",
    "League_of_One", "Conclave", "Admiralty", "Fifth_Fleet", "C_Sec",
    "Angara_Roekaar", "Outlaws", "Kett_Secret_Intelligence",
}
SHIP = {
    "SSV_Normandy", "Keelah_Siyah", "Ark_Hyperion", "Ark_Leusinia",
    "Ark_Natanus", "Ark_Paarchero", "Ark_Keelah_Siyah", "Normandy",
    "Normandy_SR", "Tempest", "ND1_Nomad",
    # distinct ship classes, not generic "Starships_" doctrine/tech content --
    # explicit membership here overrides the blanket Starships_ -> Technology
    # prefix rule below
    "Starships_Dreadnought", "Starships_Quarian_Liveships",
    "Starships_Carriers", "Starships_Fighters", "Starships_Frigates",
}
PLACE = {
    "Citadel", "Omega", "Earth", "Mars", "Palaven", "Tuchanka", "Thessia",
    "Heleus_Cluster", "Terminus_Systems", "Perseus_Veil", "Rakhana", "Luna",
    "Sol", "Arcturus", "Shanxi", "Eden_Prime", "Taetrus", "Bahak", "Aratoht",
    "Milky_Way", "Andromeda", "Andromeda_Galaxy", "Gagarin_Station",
    "Arcturus_Station", "Elysium", "Sidon", "Pragia", "Mindoir", "Aeia",
    "Amun", "Torfan", "Akuze", "Kahje", "Parnack", "Nexus", "Jartar", "Aya",
    "Rannoch", "Sur_Kesh", "Pluto", "Mercury", "Venus", "Jupiter", "Saturn",
    "Titan", "Sol_System", "Planets", "Planet", "Region", "Stations",
    "Uncharted_Worlds", "Feros", "Noveria", "Virmire", "Illium", "Korlus",
    "Lesuss", "Freedoms_Progress", "Gellix", "Haestrom", "Horizon", "Benning",
    "Cyone", "Ilos", "Ontarom", "Purgatory", "Sanctum", "Wards", "Presidium_Ring",
    "Presidium", "Serpent_Nebula", "Foundations",
    # Heleus Cluster (Andromeda)
    "Eos", "Kadara", "Voeld", "Havarl", "Elaaden", "Meridian", "Port_Meridian",
    "H_047c", "Khi_Tasira", "Verakan", "Habitat_7",
}
CHARACTER = {
    "Commander_Shepard", "David_Anderson", "Kahlee_Sanders", "Kai_Leng",
    "Saren_Arterius", "Jon_Grissom", "Paul_Grayson", "Gillian_Grayson",
    "Shu_Qian", "Desolas_Arterius", "Jack_Harper", "Zaeed_Massani",
    "Vido_Santiago", "Jeff_Moreau", "Aria_TLoak", "Illusive_Man",
    "Liara_TSoni", "Kaidan_Alenko", "Ashley_Williams", "Miranda_Lawson",
    "Jacob_Taylor", "Thane_Krios", "James_Vega", "Alec_Ryder",
    "Steven_Hackett", "Sovereign", "Harbinger", "Bailey", "Pallin",
    "Donnel_Udina", "Primarch_Fedorian", "Jack", "TaliZorah",
    "Beelo_Gurji", "Nakmor_Drack", "Samara", "Kasumi_Goto", "Yuri_Gagarin",
    "Neil_Armstrong", "Ivor_Johnstagg", "Michael_Moser_Lang",
    "Charles_Saracino", "Claude_Menneau", "Inez_Simmons", "Randall_Ezno",
    "Evfra", "Jaal_Ama_Darav", "QetsiOlam_vas_Keelah_Siyah", "Soval_Raxios",
    "Admiral_Kastanie_Drescher", "Admiral_Kahoku", "Edan_Haddah", "Intelligence",
    "EDI", "Garrus_Vakarian", "Mordin_Solus", "Karin_Chakwas", "Morinth",
    "Wrex", "Grunt", "Legion", "Javik",
    # Andromeda cast
    "Scott_Ryder", "Sara_Ryder", "Cora_Harper", "Peebee", "Vetra_Nyx",
    "Gil_Brodie", "Lexi_TPerro", "Suvi_Anwar", "Liam_Kosta", "Ellen_Ryder",
    "SAM", "Kallo_Jath", "Reyes_Vidal", "Sloane_Kelly", "William_Spender",
    "Akksul", "Nakmor_Kesh", "Tiran_Kandros", "Foster_Addison",
    "Director_Tann", "Krogan_Nakmor_Morda", "Evfra", "Angara_Sjefa",
    "Jien_Garson",
}

ALWAYS_INCLUDE = {"Omega_4_Relay"}

CATEGORY_SETS = [
    ("Character", CHARACTER), ("Faction", FACTION), ("Species", SPECIES),
    ("Place", PLACE), ("Conflict", CONFLICT), ("Technology", TECH), ("Ship", SHIP),
]
# extra prefix -> category rules for compounds with no bare-word category member
PREFIX_RULES = [
    ("Weapons_", "Technology"), ("Starships_", "Technology"), ("Vehicles_", "Technology"),
    ("Computers_", "Technology"), ("Biotics_", "Technology"), ("Space_Combat", "Technology"),
    ("Communications_", "Technology"), ("FTL_", "Technology"), ("Technology_", "Technology"),
    ("Planets_", "Place"), ("Planet_", "Place"), ("Region_", "Place"), ("Stations_", "Place"),
    ("Citadel_Station_", "Place"), ("Mercenaries_", "Faction"), ("Cerberus_", "Faction"),
    ("Normandy_", "Ship"), ("Ark_", "Ship"), ("Sleepwalker_", "Ship"),
    ("Alliance_", "Faction"),
]


def categorize(slug: str) -> str:
    for cat, members in CATEGORY_SETS:
        if slug in members:
            return cat
    for cat, members in CATEGORY_SETS:
        for m in members:
            if slug.startswith(m + "_"):
                return cat
    for prefix, cat in PREFIX_RULES:
        if slug.startswith(prefix):
            return cat
    return "Other"


def load_records(path, source_label, text_fields):
    records = json.loads(path.read_text(encoding="utf-8"))
    for r in records:
        r["_source"] = source_label
    return records


def make_example(r, source):
    if source == "timeline":
        return {"source": "timeline", "year": r["year"], "approx": r["approx"], "text": r["text"]}
    if source == "script":
        return {"source": "script", "scene": r["scene"], "text": r["text"]}
    # codex and andromeda share the same entry_name/category/is_primary shape --
    # full "Category: Name" title, not just the bare sub-entry name -- "Crew
    # Considerations" alone is ambiguous without knowing it's under "Starships"
    full_title = r["entry_name"] if r["is_primary"] else f"{r['category']}: {r['entry_name']}"
    return {"source": source, "entry": full_title, "category": r["category"], "text": r["text"]}


def main():
    timeline = load_records(TIMELINE_SRC, "timeline", ("year", "text"))
    codex = load_records(CODEX_SRC, "codex", ("entry_name", "text"))
    andromeda = load_records(ANDROMEDA_SRC, "andromeda", ("entry_name", "text")) if ANDROMEDA_SRC.exists() else []
    script = []  # fan-script supplement removed: the docx codex independently
    # confirms Shepard's Spectre status (see the "Rise of the Alliance: Renegade:"
    # entry), so the fan-written material is no longer needed
    all_records = timeline + codex + andromeda + script

    freq = Counter()
    examples = defaultdict(list)
    for r in all_records:
        for e in r["entities"]:
            freq[e] += 1
            if MAX_EXAMPLES_PER_NODE is None or len(examples[e]) < MAX_EXAMPLES_PER_NODE:
                examples[e].append(make_example(r, r["_source"]))

    top_entities = [e for e, _ in freq.most_common(TOP_N_NODES)]
    # guarantee every curated named character makes it in, even at low raw
    # frequency (e.g. EDI at 5 mentions missing a 250-node cutoff that needs 6) --
    # this is a small, deliberately-curated list, not an arbitrary frequency bar
    top_set = set(top_entities)
    for character in sorted(CHARACTER):
        if character in freq and character not in top_set:
            top_entities.append(character)
            top_set.add(character)
    # a few significant, low-frequency entities that would otherwise fall just
    # below the top-N cutoff (e.g. Omega_4_Relay -- a genuinely distinct place
    # from Omega itself, just rarely mentioned by name) -- same guarantee as
    # CHARACTER above, kept to a short, deliberately-curated list
    for always in sorted(ALWAYS_INCLUDE):
        if always in freq and always not in top_set:
            top_entities.append(always)
            top_set.add(always)

    co = Counter()
    for r in all_records:
        ents = sorted(set(r["entities"]) & top_set)
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                co[(ents[i], ents[j])] += 1

    nodes = [
        {
            "id": e,
            "count": freq[e],
            "timeline_count": sum(1 for r in timeline if e in r["entities"]),
            "codex_count": sum(1 for r in codex if e in r["entities"]),
            "andromeda_count": sum(1 for r in andromeda if e in r["entities"]),
            "script_count": sum(1 for r in script if e in r["entities"]),
            "category": categorize(e),
            "examples": examples[e],
        }
        for e in top_entities
    ]
    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in co.items()
        if w >= MIN_EDGE_WEIGHT
    ]

    eras = []
    seen = set()
    for r in timeline:
        if r["era"] not in seen:
            seen.add(r["era"])
            eras.append(r["era"])

    events = [
        {
            "year": r["year"], "year_end": r["year_end"], "approx": r["approx"],
            "era": r["era"], "title": r["title"], "text": r["text"],
            "entities": r["entities"],
        }
        for r in timeline
    ]

    blob = {
        "nodes": nodes, "edges": edges, "eras": eras, "events": events,
        "stats": {
            "timeline_events": len(timeline), "codex_entries": len({r["entry_id"] for r in codex}),
            "codex_sentences": len(codex),
            "andromeda_entries": len({r["entry_id"] for r in andromeda}),
            "andromeda_sentences": len(andromeda),
        },
    }
    OUT.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    print(f"{len(nodes)} nodes, {len(edges)} edges (weight>={MIN_EDGE_WEIGHT}), "
          f"{len(events)} timeline events, {len(codex)} codex sentence records, "
          f"{len(andromeda)} andromeda sentence records -> {OUT}")
    uncategorized = [n["id"] for n in nodes if n["category"] == "Other"]
    print(f"'Other' bucket ({len(uncategorized)}): {uncategorized}")


if __name__ == "__main__":
    main()
