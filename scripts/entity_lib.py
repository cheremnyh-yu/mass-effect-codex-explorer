# -*- coding: utf-8 -*-
"""Shared entity-extraction logic for both the timeline (build_timeline.py) and
the codex docx (build_codex.py) pipelines, so a fix made in one place (e.g. the
Alliance/Systems_Alliance alias, the Citadel/Citadel_Council decomposition rule)
applies consistently to both corpora and their entity IDs line up.
"""
import re

ARTICLES = {"The", "A", "An"}

# words safe to strip from the *front* of a multi-word span regardless of position --
# unlike ordinals ("First Contact War"), these subordinating conjunctions/titles are
# never part of a real proper name, only glued on by sentence-initial capitalization
# or by military/political rank (e.g. "While Shepard follows..." -> just "Shepard";
# "Primarch Fedorian declares..." -> just "Fedorian")
STRIP_LEADING = ARTICLES | {
    "When", "While", "After", "Before", "During", "Following", "Since",
    "Although", "Because", "Until", "Unlike", "Despite", "Eventually",
    "However", "Meanwhile", "Once", "In", "On", "As", "Where", "But", "Their",
    "Many", "At",
    "General", "Executor", "Councilor", "Primarch", "Ambassador", "Admiral",
    "Captain", "Lieutenant", "Fleet", "Dr", "Mr", "Mrs", "Ms", "Commander", "Flight",
    "Spectre", "Spectres", "Overlord", "Pathfinder", "Moshae", "Director",
    "Most", "Each",
}

# never valid as a *standalone* single-word entity, even if corpus-confirmed non-initial
# (e.g. "First" recurs mid-sentence in "...First ESA mission..." but isn't itself an entity)
REJECT_SINGLE = {
    "First", "Second", "Third", "Fourth", "Fifth", "Last", "Next", "Director",
    "Office", "More", "Large", "Light", "Man", "CE", "BCE", "Pushed", "Overlord",
}

# real single-word character names some corpora only ever mention sentence-initially
# (so the noninitial-confirmation heuristic would otherwise drop them, same failure mode
# as common words like "Thus" -- curated by hand as spotted, same as the WHITELIST terms)
ALWAYS_KEEP_SINGLE = {"Jack"}

# short-form / title-form / alt-name variants -> the fullest name for that entity
# (characters, organizations, places, ships alike), checked against every occurrence's
# surrounding sentence to make sure a shared surname isn't actually two different
# people (e.g. Paul_Grayson vs. Gillian_Grayson stay separate; bare "Grayson" only
# ever means Paul in the timeline) and that a shared word isn't a sub-entity
# (e.g. Turian_Hierarchy stays separate from Turian -- that's government-vs-species,
# not a naming variant, the same distinction that keeps Citadel next to Citadel_Council)
ENTITY_ALIASES = {
    "Anderson": "David_Anderson",
    "Admiral_Anderson": "David_Anderson",
    "Sanders": "Kahlee_Sanders",
    "Grissom": "Jon_Grissom",
    "Admiral_Jon_Grissom": "Jon_Grissom",
    "Harper": "Jack_Harper",
    "Desolas": "Desolas_Arterius",
    "Zaeed": "Zaeed_Massani",
    "Vido": "Vido_Santiago",
    "Qian": "Shu_Qian",
    "Spectre_Saren_Arterius": "Saren_Arterius",
    "Saren": "Saren_Arterius",
    "Leng": "Kai_Leng",
    "Joker": "Jeff_Moreau",
    "Moreau": "Jeff_Moreau",
    "Captain_Bailey": "Bailey",
    "Executor_Pallin": "Pallin",
    "Shepard": "Commander_Shepard",
    "Aria": "Aria_TLoak",
    "Jeff": "Jeff_Moreau",
    "SR_2": "Normandy_SR_2",
    "SR_1": "Normandy_SR_1",
    "Silaris": "Silaris_Armor",
    "Thanix": "Thanix_Magnetic_Hydrodynamic_Weapon",
    "Broker": "Shadow_Broker",
    "Reaper_Sovereign": "Sovereign",
    "Grayson": "Paul_Grayson",
    "Reapers": "Reaper",
    "Alliance": "Earth_Systems_Alliance",
    "Systems_Alliance": "Earth_Systems_Alliance",
    "Systems_Alliance_N": "Earth_Systems_Alliance",
    "Union": "Salarian_Union",
    "Initiative": "Andromeda_Initiative",
    "Grissom_Academy": "Jon_Grissom_Academy",
    "Eldfell_Ashland_Energy": "Eldfell_Ashland_Energy_Corporation",
    "Xenophobic_Homeward_Sol": "Homeward_Sol",
    "First_ESA": "ESA",
    "Sol_System": "Sol",
    "Andromeda_Galaxy": "Andromeda",
    "Ark_Keelah_Siyah": "Keelah_Siyah",
    "Monolith": "Arca_Monolith",
    "Biotic_Acclimation": "BAaT",
    "Temperance_Training": "BAaT",
    "Jilani": "Khalisah_al_Jilani",
    "Khalisah": "Khalisah_al_Jilani",
    # discovered while merging in the codex docx entries
    "Udina": "Donnel_Udina",
    "Citadel_Councilor_Donnel_Udina": "Donnel_Udina",
    "David_Edward_Anderson": "David_Anderson",
    # plural species/race names used as a codex category prefix ("Turians:
    # Government:") need to fold to the singular so they group with the
    # species' own entry ("Turian") instead of forking into "Turians_Government"
    "Turians": "Turian", "Salarians": "Salarian", "Quarians": "Quarian",
    "Krogans": "Krogan", "Batarians": "Batarian", "Protheans": "Prothean",
    "Humans": "Human", "Collectors": "Collector", "Thresher_Maws": "Thresher_Maw",
    # "nar Rayya" is a ship affiliation, not a permanent part of her identity --
    # she's "vas Normandy" later on, so the base name is the stable canonical form
    "TaliZorah_nar_Rayya": "TaliZorah",
    "STG": "Special_Tasks_Group",
    "League": "League_of_One",
    # same self-introduced-abbreviation pattern as C-Sec: "The Enhanced Defense
    # Intelligence, or EDI, serves as..." -- EDI is the name actually used elsewhere
    "Enhanced_Defense_Intelligence": "EDI",
    # "Computers: Artificial Intelligence (AI):" and "Vehicles: Combat Drones:" are
    # secondary codex sub-entries about a topic that already has its own bare
    # whitelist entity (AI, Drones) -- same count/content fragmented across two IDs
    "Computers_Artificial_Intelligence": "AI",
    "Vehicles_Combat_Drones": "Drones",
    # collapse the individual weapon-system/model nodes (compound "Weapons: X"
    # sub-entries, plus standalone named ordnance entries) into one Weapons hub --
    # each specific model was too small/low-value a node on its own; Omni-Tool
    # stays separate since it's a distinct, much more central gadget, not just
    # another gun
    "Weapons_Ablative_Armor": "Weapons",
    "Weapons_Disruptor_Torpedoes": "Weapons",
    "Weapons_GARDIAN": "Weapons",
    "GARDIAN": "Weapons",
    "Weapons_Javelin": "Weapons",
    "Weapons_Mass_Accelerators": "Weapons",
    "Mass_Accelerators": "Weapons",
    "M_920_Cain": "Weapons",
    "M_451_Firestorm": "Weapons",
    "A_61_Mantis_Gunship": "Weapons",
    "Blackstar": "Weapons",
    "Kassa_Fabrications_Locust": "Weapons",
    "Locust": "Weapons",
    "ML_77_Missile_Launcher": "Weapons",
    "M_560_Hydra": "Weapons",
    "M_622_Avalanche": "Weapons",
    "Mantis": "Weapons",
    # bare shorthand that this corpus only ever uses to mean one specific thing
    # (checked context-by-context, not assumed): "the Hierarchy" always means
    # the Turian Hierarchy here, "Terminus" the Terminus Systems, "the Fleet"
    # the quarian Migrant Fleet, "CBT" Cyclonic Barrier Technology
    "Hierarchy": "Turian_Hierarchy",
    "Terminus": "Terminus_Systems",
    "Fleet": "Migrant_Fleet",
    "CBT": "Kinetic_Barriers",
    # plural/singular entry-vs-whitelist mismatches, same failure mode as EDI/
    # C-Sec: a primary entry titled "Mass Relays:"/"Mass Effect Fields:" self-
    # tags its own (plural) slug while every inline body mention gets the
    # singular WHITELIST canonical, splitting one concept across two IDs
    "Mass_Relays": "Mass_Relay",
    "Mass_Effect_Fields": "Mass_Effect_Field",
    "VI": "Virtual_Intelligence",
    "VIs": "Virtual_Intelligence",
    "Suns": "Blue_Suns",
    "Argus": "Argus_Planet_Scan_Technology",
    "DRA": "Starships",
    "Military_Ship_Classifications": "Starships",
    "Body_Armor": "Armor",
    "Tech_Armor_and_Fortification": "Armor",
    "Silaris_Armor": "Armor",
    # Andromeda codex: bare first-name/surname/short-form mentions elsewhere in
    # the corpus vs. the full name the Andromeda entry itself establishes --
    # same fragmentation pattern as EDI/Kodiak/C-Sec in the main codex
    "Angara_Evfra_de_Tershaa": "Evfra",
    "Jaal": "Jaal_Ama_Darav",
    "Sara": "Sara_Ryder",
    "Nexus_Andromeda_Initiative_Director_Tann": "Director_Tann",
    "Roekaar": "Angara_Roekaar",
    "Hyperion": "Ark_Hyperion",
    "Andromeda_Initiative_Jien_Garson": "Jien_Garson",
    "Garson": "Jien_Garson",
    "Habitat": "Habitat_7",
    "Resistance": "Angaran_Resistance",
    "Pathfinders": "Pathfinder",
    "Heleus": "Heleus_Cluster",
    "Outcasts": "Outlaws_Outcasts",
    "Collective": "Outlaws_Collective",
    # PDF text-extraction artifact in the Andromeda codex: "AI" (capital I)
    # misreads as "Al" (capital A, lowercase L) in this font
    "Al": "AI",
    # "Technology: X" sub-entries that are each a distinct, nameable concept
    # in their own right, not a generic facet of "Technology" -- strip the
    # redundant category prefix instead of either folding or keeping it
    "Technology_Terraforming": "Terraforming",
    "Technology_Prothean_Beacon": "Prothean_Beacon",
    "Technology_Charting_Andromeda": "Charting_Andromeda",
    "Technology_Weapon_and_Armor_Mods": "Weapon_and_Armor_Mods",
    "Technology_Consumable_resources": "Consumable_Resources",
    "Technology_Materials": "Materials",
    # "Nexus: X" sub-entries -- named people and the specific Hydroponics
    # facility/Uprising event get promoted to a bare name (same treatment as
    # Terraforming above); "Leadership" is generic governance content about
    # the Nexus itself, so it folds into the Nexus hub instead
    "Nexus_Hydroponics": "Hydroponics",
    "Nexus_Foster_Addison": "Foster_Addison",
    "Andromeda_Initiative_Nexus_Uprising": "Nexus_Uprising",
    "Nexus_Nakmor_Kesh": "Nakmor_Kesh",
    "Nexus_Tiran_Kandros": "Tiran_Kandros",
    "Nexus_Leadership": "Nexus",
    # CBT is explicitly described as an advanced variant of the same
    # underlying kinetic-barrier tech, not a separate concept
    "Cyclonic_Barrier_Technology": "Kinetic_Barriers",
    # match the already-bare "AI" node's treatment -- distinct, nameable
    # concepts, not generic facets of "Computers"
    "Computers_Virtual_Intelligence": "Virtual_Intelligence",
    "Computers_Haptic_Adaptive_Interface": "Haptic_Adaptive_Interface",
    # "Angaran Culture: Law and Politics/Economics/Military Doctrine" already
    # fold into an "Angaran_Culture" hub via the generic-subtopic rule, but
    # that hub is itself just more Angara culture content, not a distinct topic
    "Angaran_Culture": "Angara",
    "Scott": "Scott_Ryder",
    # same alias-collision pattern as Black_Hole above: "Pathfinders" ->
    # "Pathfinder" also renames the category prefix of "Pathfinders: Asari/
    # Salarian/Turian Pathfinder", producing a redundant "Pathfinder_Asari_
    # Pathfinder" -- strip the doubled word instead
    "Pathfinder_Asari_Pathfinder": "Asari_Pathfinder",
    "Pathfinder_Salarian_Pathfinder": "Salarian_Pathfinder",
    "Pathfinder_Turian_Pathfinder": "Turian_Pathfinder",
    # more Andromeda-corpus dedup: docx typo ("Nakmore Kesh"), bare first-name
    # fragments, fuller-name variant, singular/plural, and a spelling variant
    # that already exists in the main codex's SHIP set
    "Nakmore_Kesh": "Nakmor_Kesh",
    "Kallo": "Kallo_Jath",
    "Sloane": "Sloane_Kelly",
    "Jarun_Tann": "Director_Tann",
    "Outlaw": "Outlaws",
    "Remnant_Assemblers": "Remnant_Assembler",
    "Ark_Leusiana": "Ark_Leusinia",
    "Tann": "Director_Tann",
    # "Upgrades:" is really just describing omni-tool field-modification kits,
    # not a separate topic from the omni-tool itself
    "Upgrades": "Omni_tool",
    "Omni_Tool_Weapons": "Omni_tool",
    # "Officially named the Kodiak, the drop-shuttle is better known..." -- same
    # vehicle as the UT-47, fragmented across its nickname, model number, and a
    # plural form; "System_Alliance" is a one-off typo for Earth_Systems_Alliance
    "Kodiak": "UT_47_Kodiak",
    "Kodiaks": "UT_47_Kodiak",
    "UT_47": "UT_47_Kodiak",
    "Systems_Alliance_UT_47": "UT_47_Kodiak",
    "System_Alliance": "Earth_Systems_Alliance",
    # C-Sec = Citadel Security Services, its own docx title literally gives the
    # abbreviation in parentheses; C-Sec is the far more recognizable form
    "Citadel_Security_Services": "C_Sec",
    "Citadel_Station_Citadel_Security_Services": "C_Sec",
    "Citadel_Security": "C_Sec",
    "Randal": "Randall_Ezno",  # typo'd mid-paragraph in the source ("Randall" -> "Randal")
    # generic bare mentions of the ship fold into its full designation; the
    # specific hull variants (Normandy_SR_1, Normandy_SR_2 -- two different,
    # non-interchangeable ships) are left alone, not merged into this
    "Normandy": "SSV_Normandy",
    # "Council" alone is shorthand for the Citadel Council in the overwhelming
    # majority of mentions (confirmed: 78 of 79 bare-"Council" sentences clearly
    # mean the Citadel Council; the one exception, "Singapore Marketing Council",
    # is already its own distinct compound entity) -- same reasoning as the
    # Alliance/Systems_Alliance merge, unlike Citadel/Citadel_Council which stay
    # separate because Citadel-the-station is genuinely a different thing
    "Council": "Citadel_Council",
}

# fourth-wall references to the games/media themselves (not in-universe entities) --
# same category of thing as the "events of Mass Effect: X occur" timeline sentences
# that already get filtered out, just showing up as entity tags instead of sentences
DROP_ENTITIES = {
    "Mass_Effect", "Mass_Effect_2", "Mass_Effect_3", "Mass_Effect_Andromeda",
    "Mass_Effect_Galaxy", "Mass_Effect_2_Updates", "Mass_Effect_3_Updates",
    "Mass_Effect_and_Mass_Effect_2",
    "Battle",  # too generic to be its own node -- every war has "a battle"
    "Paragon", "Renegade",  # game morality-meter mechanics, not lore entities
    "Timeline",  # the docx's own "Timeline:" section self-tagging, not a lore entity
    # mutually-exclusive ME3 ending variants -- like Paragon/Renegade, these are
    # branch-outcome blurbs, not persistent lore facts
    "Quarians_and_Geth_Survive", "Quarians_Destroyed", "Geth_Destroyed",
    # player background/psych-profile combos (pre-game character-creation choices,
    # never persistent lore) and quest-choice branch outcomes
    "Spacer_Sole_Survivor", "Spacer_War_Hero", "Spacer_Ruthless",
    "Colonist_Sole_Survivor", "Colonist_War_Hero", "Colonist_Ruthless",
    "Earthborn_Sole_Survivor", "Earthborn_War_Hero", "Earthborn_Ruthless",
    "Anderson_Chosen_Councilor", "Udina_Chosen_Councilor",
}

NEGATION_RE = re.compile(
    r"\b(no|not|never|without|lacks?|lacking|none of|neither|isn't|aren't|"
    r"wasn't|weren't|doesn't|don't|didn't)\s+\S*\s*$",
    re.IGNORECASE,
)

STOPWORDS = {
    "The", "A", "An", "In", "On", "At", "After", "Before", "During", "Following",
    "With", "Without", "This", "That", "These", "Those", "Its", "Their", "His",
    "Her", "He", "She", "I", "We", "You", "Him", "Them", "Us",
    "They", "It", "When", "While", "Some", "Many", "Most", "Later",
    "Eventually", "However", "Although", "Because", "Since", "Until", "Unlike",
    "Despite", "Due", "Amid", "Among", "Once", "Over", "Under", "Between",
    "Within", "As", "By", "For", "Not", "Only", "Both", "All", "Each", "Every",
    "Another", "Other", "Two", "Three", "Four", "Five", "One", "Roughly",
    "About", "Around", "Given", "Meanwhile", "Dr", "Mr", "Mrs", "Ms", "Lt",
    "Capt", "Col", "Gen", "Adm", "Sgt", "Prof", "If", "Unless", "Should",
    "Whether", "Whatever", "Whenever", "Wherever", "Whoever", "Regardless", "You",
    "What", "Who", "Why", "How", "Part", "Nobody", "Someone", "Anyone", "Everyone",
}

ABBREVS = ("Dr.", "Mr.", "Mrs.", "Ms.", "Lt.", "Capt.", "Col.", "Gen.", "Adm.",
           "Sgt.", "Prof.", "vs.", "etc.", "No.")

# consecutive runs of capitalized words only -- no general lowercase connectors, so
# "Zaeed Massani and Vido Santiago" naturally splits into two separate spans instead
# of merging into one. "nar"/"vas" are narrow exceptions for quarian full names
# ("Tali'Zorah nar Rayya", "Qetsi'Olam vas Keelah Si'yah"). A hyphenated suffix can
# be another capitalized word OR a bare digit run ("Normandy SR-1", "M-920 Cain") --
# without the digit case, "Normandy SR-1" and "Normandy SR-2" (two different ships)
# both collapsed into the same ambiguous "Normandy_SR" fragment.
_WORD = r"[A-Z][A-Za-z'’]*(?:-(?:[A-Z][A-Za-z'’]*|\d+))?"
PROPER_RE = re.compile(
    rf"\b{_WORD}"
    rf"(?:\s+(?:nar|vas)\s+{_WORD}"
    rf"|\s+{_WORD}){{0,4}}"
)

# Curated case-insensitive terms for categories source text often writes in lowercase
# (species/race names, chemical & tech substances, war/conflict names -- sometimes
# under an alternate turian/human/etc. name for the same conflict). The capitalization
# heuristic above structurally can't see these when used as common nouns.
WHITELIST = {
    "Asari": [r"asari"],
    "Salarian": [r"salarians?"],
    "Turian": [r"turians?"],
    "Krogan": [r"krogan"],
    "Quarian": [r"quarians?"],
    "Geth": [r"geth"],
    "Batarian": [r"batarians?"],
    "Volus": [r"volus"],
    "Elcor": [r"elcor"],
    "Hanar": [r"hanar"],
    "Drell": [r"drell"],
    "Vorcha": [r"vorcha"],
    "Yahg": [r"yahg"],
    "Rachni": [r"rachni"],
    "Prothean": [r"protheans?"],
    "Human": [r"humans?", r"humanity"],
    "Angara": [r"angarans?", r"angara"],
    "Kett": [r"kett"],
    "Raloi": [r"raloi"],
    "Leviathan": [r"leviathans?"],
    "Leviathan_of_Dis": [r"leviathan of dis"],
    "Reaper": [r"reapers?"],
    "Collector": [r"collectors?"],
    "Husk": [r"husks?"],
    "Thresher_Maw": [r"thresher\s+maws?"],
    "Arthenn": [r"arthenn"],
    "Thoihan": [r"thoi'han"],
    "Inusannon": [r"inusannon"],
    "Zeioph": [r"zeioph"],
    "Kirik": [r"kirik"],
    "Element_Zero": [r"element\s+zero", r"eezo"],
    "Helium_3": [r"helium-3"],
    "Antimatter": [r"antimatter"],
    "Red_Sand": [r"red\s+sand"],
    "Genophage": [r"genophage"],
    "Biotics": [r"biotics?"],
    "Mass_Relay": [r"mass\s+relays?"],
    "Mass_Effect_Field": [r"mass\s+effect\s+fields?"],
    "Hegemony": [r"hegemony"],
    "Council": [r"council"],
    "Parliament": [r"parliament"],
    "Citadel": [r"citadel"],
    "Omega": [r"omega"],
    # "Spectres are agents from the Office of Special Tactics and Reconnaissance" --
    # this office IS the Spectre organization, not a separate entity; without this
    # whole-phrase match, PROPER_RE's word-by-word scan (which can't cross the
    # lowercase "of"/"and") fragments it into bogus "Office"/"Special_Tactics"/
    # "Reconnaissance" nodes instead
    # bare "special tactics and reconnaissance" is what actually identifies the
    # Spectre office (not the "Office of"/"Citadel" framing words around it) --
    # the "citadel special tactics and reconnaissance" variant is kept too so that
    # longer span also gets suppressed as a leftover "Citadel_Special_Tactics"
    # fragment (Citadel itself still tags separately, same decomposition as
    # Citadel/Citadel_Council)
    "Spectres": [
        r"spectres?", r"special tactics and reconnaissance",
        r"citadel special tactics and reconnaissance",
    ],
    # ranks / titles -- decomposed the same way as Citadel/Citadel_Council: the
    # title coexists with the person's own name rather than being silently
    # dropped ("Admiral Anderson" tags both "Admiral" and "David_Anderson")
    "Admiral": [r"admirals?"],
    "Captain": [r"captains?"],
    "General": [r"generals?"],
    "Executor": [r"executors?"],
    "Councilor": [r"councilors?"],
    "Primarch": [r"primarchs?"],
    "Ambassador": [r"ambassadors?"],
    "Lieutenant": [r"lieutenants?"],
    "Doctor": [r"doctors?", r"dr\."],
    "Commander": [r"commanders?"],
    "Rachni_Wars": [r"rachni\s+wars?"],
    "Krogan_Rebellions": [r"krogan\s+rebellions?"],
    "Unification_War": [r"unification\s+war"],
    "First_Contact_War": [r"first\s+contact\s+war", r"relay\s+314\s+incident"],
    "Morning_War": [r"morning\s+war", r"geth\s+war"],
    "Eden_Prime_War": [r"eden\s+prime\s+war"],
    "Anhur_Rebellions": [r"anhur\s+rebellions?"],
    "Skyllian_Blitz": [r"skyllian\s+blitz"],
    "Metacon_War": [r"metacon\s+war"],
    "Theshaca_Raids": [r"theshaca\s+raids?"],
    "Relay_314": [r"relay\s+314"],
    "Omega_4_Relay": [r"omega[\s-]*4\s+relay"],
}
WHITELIST_PATTERNS = [
    (canonical, re.compile(r"\b(?:" + "|".join(pats) + r")\b", re.IGNORECASE))
    for canonical, pats in WHITELIST.items()
]


def slugify(name: str) -> str:
    n = name.strip()
    n = re.sub(r"^(the|a|an)\s+", "", n, flags=re.IGNORECASE)
    n = re.sub(r"['’]s\b", "", n)  # possessive: Ryder's -> Ryder, not Ryders
    n = n.replace("'", "").replace("’", "")
    n = re.sub(r"[^A-Za-z0-9]+", "_", n).strip("_")
    return n


def extract_entities(sentence: str, occurrence_log=None):
    """occurrence_log, if given, is a dict[slug] -> {"initial": bool, "noninitial": bool}
    used for a later corpus-wide pass that drops single-word slugs which only ever
    appeared capitalized because they happened to start a sentence."""
    found = {}
    whitelist_spans = []

    def is_negated(start):
        # "Drones... have no Artificial Intelligence" shouldn't read as Drones
        # being associated with AI -- skip tagging an entity whose mention is
        # immediately preceded by an explicit negation of it
        window = sentence[max(0, start - 25):start]
        return bool(NEGATION_RE.search(window))

    for canonical, pattern in WHITELIST_PATTERNS:
        for m in pattern.finditer(sentence):
            if is_negated(m.start()):
                continue
            found[canonical] = canonical.replace("_", " ")
            whitelist_spans.append((m.start(), m.end()))

    def fully_covered_by_whitelist(start, end):
        return any(ws <= start and we >= end for ws, we in whitelist_spans)

    def process_words(words, is_initial):
        original_len = len(words)
        while words and words[0] in STRIP_LEADING and len(words) > 1:
            words = words[1:]
        if len(words) != original_len:
            is_initial = False
        if not words or all(w in STOPWORDS for w in words):
            return
        if len(words) == 1 and (words[0] in STOPWORDS or words[0] in REJECT_SINGLE):
            return
        clean_span = " ".join(words)
        slug = slugify(clean_span)
        if len(slug) < 2:
            return
        found[slug] = clean_span
        if occurrence_log is not None and len(words) == 1:
            rec = occurrence_log.setdefault(slug, {"initial": False, "noninitial": False})
            if is_initial:
                rec["initial"] = True
            else:
                rec["noninitial"] = True

    for m in PROPER_RE.finditer(sentence):
        start, end = m.start(), m.end()
        while end > start and sentence[end - 1] in "'’":
            end -= 1
        if fully_covered_by_whitelist(start, end):
            continue
        if is_negated(start):
            continue
        span = sentence[start:end].strip()
        words = span.split()
        is_initial = m.start() == 0

        split_at = next(
            (i for i, w in enumerate(words[:-1]) if re.search(r"['’]s$", w)), None
        )
        if split_at is not None:
            process_words(words[:split_at + 1], is_initial)
            process_words(words[split_at + 1:], False)
        else:
            process_words(words, is_initial)
    return found


def split_sentences(text: str):
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"‘’])', text)
    sentences = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if sentences and sentences[-1].endswith(ABBREVS):
            sentences[-1] = sentences[-1] + " " + s
        else:
            sentences.append(s)
    return sentences


PRONOUN_LEAD_RE = re.compile(r"^(He|She|Him|Her|His|They|Them|Their)\b")


def propagate_pronoun_subject(sentence_entity_pairs):
    """sentence_entity_pairs: ordered list of (sentence_text, entities_dict) from
    ONE source paragraph. Splitting a paragraph into standalone sentences strips
    the context a pronoun needs -- "Randall Ezno... He provides the Alliance with
    intel..." loses Randall entirely once "He provides..." becomes its own
    sentence. Heuristic fix: the first entity in the paragraph whose name isn't a
    generic whitelist term and has a multi-word name (i.e. looks like an actual
    proper name, not a species/place common noun) becomes the paragraph's
    "subject", and gets added to every later sentence that opens on a bare
    pronoun referring back to it. Mutates entities_dict in place."""
    subject = None
    for sent, ents in sentence_entity_pairs:
        if subject is None:
            for slug, name in ents.items():
                if " " in name and slug not in WHITELIST:
                    subject = (slug, name)
                    break
        elif PRONOUN_LEAD_RE.match(sent):
            ents.setdefault(subject[0], subject[1])
    return sentence_entity_pairs


def finalize_entities(records, occurrence_log, text_key="text", entities_key="entities", always_confirmed=()):
    """Apply the corpus-wide single-word confirmation filter + entity aliases +
    the Commander-is-ambiguous special case to a list of records in place, and
    return (dropped_entity_mentions, dropped_generic_word_count) for logging."""
    confirmed_single = {slug for slug, occ in occurrence_log.items() if occ["noninitial"]}
    confirmed_single |= set(WHITELIST.keys())
    confirmed_single |= ALWAYS_KEEP_SINGLE
    # a curated alias is itself vetting: don't let the sentence-initial-only filter
    # kill "Randal" (typo, only ever appears once, sentence-initial) before its
    # alias to "Randall_Ezno" gets a chance to apply
    confirmed_single |= set(ENTITY_ALIASES.keys())
    # deliberately injected tags (e.g. a "Category: Sub-topic" entry's category,
    # tagged onto every sentence even when the sentence itself never says the
    # word) are trusted by construction, not by the position heuristic
    confirmed_single |= set(always_confirmed)

    dropped = 0
    for r in records:
        kept = {}
        for slug, name in r[entities_key].items():
            if " " in name or slug in confirmed_single:
                kept[slug] = name
            else:
                dropped += 1
        slugs = {ENTITY_ALIASES.get(s, s) for s in kept}

        # "Commander Shepard"/"Commander Vyrnnus" already resolve correctly on
        # their own (STRIP_LEADING peels "Commander" off the front, leaving the
        # bare name to alias normally -- e.g. "Shepard" -> Commander_Shepard,
        # "Vyrnnus" stays Vyrnnus). This only needs to catch the genuinely bare,
        # no-name-attached case ("...the Commander makes a decision...") where
        # "Commander" is standing in for Shepard by itself -- checked directly
        # against the text so a Vyrnnus sentence's "Commander" tag doesn't also
        # pull in Commander_Shepard just because both slugs are present. Plural
        # "commanders" (e.g. "act as battlefield commanders") is a generic role
        # reference, never Shepard specifically, however bare it reads.
        if ("Commander" in slugs and "rank of Commander" not in r[text_key]
                and not re.search(r"\bCommander\s+[A-Z]", r[text_key])
                and not re.search(r"\bcommanders\b", r[text_key], re.IGNORECASE)):
            slugs.add("Commander_Shepard")

        slugs -= DROP_ENTITIES
        r[entities_key] = sorted(slugs)
    return dropped
