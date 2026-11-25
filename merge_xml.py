"""
merge_xml.py

Puts the two halves of the volume 3 place index back together:

    ortsverzeichnis_vol3.xml             entries WITHOUT a reference
    ortsverzeichnis_vol3_references.xml  reference entries ("X -> see Y")

    python merge_xml.py
    python merge_xml.py --out merged.xml --report merged_assigned.csv
    python merge_xml.py --no-suggest     # don't add id_suggested attributes


HOW THE IDS ARE ORDERED
-----------------------
An ort id looks like 10300317-2:

    103      volume 3
    00317    running number of the headword in the PRINTED index, 1..2640,
             counted over both halves together - the split only divided the
             numbers between two files, no number is used in both
    -2       row within that headword (one row per institution/office), in
             the order the rows were printed

So the printed order is recovered simply by sorting on (running number, row
number). The <index char=".."> grouping of the input files is NOT used for
ordering: it was built from the first letter as written ('St. Gallen' under
s, 'Ägina' under ä), while the volume files 'St. Gallen' under G between Gail
and Gallepaltental, and 'Ägina' among the A's.


HOW THE PRINTED INDEX IS ALPHABETISED
-------------------------------------
Learned from the order of the 2594 headwords that have a real id:

  * leading particles are ignored: St., S., Pr., de, le, la, in, zum, zur,
    s'  ('de Sanctogallo' under Sanctog.., 'zum Bruche' under Bruche)
  * umlauts and accents count as the base letter, ß as ss
    (Löbau < Lobeda < Löben)
  * I and J are one letter (Jagdberg, Jauer, Ibbs, Ibsa, Jechaburg ...),
    so they share the letter group <index char="i">; U and V stay apart
  * spaces, hyphens, dots and brackets are ignored (Gross-Behringen <
    (Gross-) Enzersdorf < Gross-Erich)
  * a bracketed prefix is sometimes filed under (Gross-) and sometimes
    skipped ((Kl.) Zacken under Z, (Unter-)Steinach under Steinach), so both
    readings are tried - see below

The printed index is not perfectly alphabetical (the script prints how many
neighbouring headwords are out of order under this key), so the key is used
to find a SLOT between two real headwords, never to re-sort the real ones.


SAME-NAMED PLACES SHARING ONE ID
--------------------------------
The id mapping matched on the place name, so different places with the same
name printed one after another (Altdorf, Argent. dioc. / Altdorf, Ratisp.
dioc.) ended up on one id, and the number of the first one was left unused.
Rows of one id are the same place when the place AND the diocese match (the
name variant decides only when a row has no diocese - a shared variant
across two dioceses is still two places). When an id holds k places and the k-1 numbers
directly below it are unused, the first printed place gets the lowest of
them and the last keeps the id; row suffixes restart at 1. This runs before
the assigned entries are placed. Every change is listed in OUT_SPLIT_REPORT.


ENTRIES WITH id_source="assigned"
---------------------------------
These got an id from a reserved block (10390001.., 10391001..) because their
real number was unknown, so their number says nothing about their position.
Each one is placed by its place name:

  1. its sort key (and the alternative readings of a bracketed prefix) is
     compared with the real headwords; every slot where
         key(previous headword) <= key < key(next headword)
     is a candidate
  2. a slot where the running numbers of the two neighbours leave a gap
     (e.g. 10300316 .. 10300318) is preferred: that missing number is very
     likely the entry's real id, since every number up to 2640 was used
  3. several assigned entries in one slot are put in alphabetical order

The reserved id is kept as the id. When a slot has exactly as many free
numbers as assigned places, the free number is written as
id_suggested="..." (use --no-suggest to leave it out). Every placement is
listed in the report CSV with its neighbours so it can be checked against
the volume.


LEMMA IDS
---------
<lemma_id> holds the column numbers of the lemmata the place occurs in.
Each becomes an 8-digit id, LEMMA_ID_BASE (10300000) + the number:

    <lemma_id>107, 161, 179, 256</lemma_id>
 -> <lemma_id>10300107, 10300161, 10300179, 10300256</lemma_id>

Separators and brackets are kept as printed: '(233 345)' becomes
'(10300233 10300345)'. Use --no-lemma-prefix to leave them as they are.


CHECKS
------
The merged file is re-read and compared with the inputs: same number of
<ort>, every id present exactly once, same number of column numbers in
<lemma_id>, every lemma id equal to its column number + LEMMA_ID_BASE, same
number of <place> and <reference> tags.
"""

import argparse
import csv
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

IN_MAIN = "ortsverzeichnis_vol3.xml"
IN_REFERENCES = "ortsverzeichnis_vol3_references.xml"
OUT_XML = "ortsverzeichnis_vol3_merged.xml"
OUT_REPORT = "ortsverzeichnis_vol3_merged_assigned.csv"
OUT_SPLIT_REPORT = "ortsverzeichnis_vol3_merged_split.csv"

# <lemma_id> column numbers become 8-digit ids: 107 -> 10300107
LEMMA_ID_BASE = 10300000

# how many following entries must agree before a new <index char> starts;
# stops a single oddly-filed headword from splitting a letter group
LETTER_LOOKAHEAD = 3


# ---------------------------------------------------------------- sort keys

PARTICLE = re.compile(
    r"^\s*(?:(?:st|s|pr)\.\s*|(?:de|le|la|in|zum|zur)\s+|s[’'`]\s*)",
    re.IGNORECASE)


def strip_particles(text):
    prev = None
    while prev != text:
        prev, text = text, PARTICLE.sub("", text, count=1)
    return text


def fold(text):
    """Lower case, umlauts/accents -> base letter, ß -> ss, letters and
    digits only."""
    text = text.replace("ß", "ss").replace("ẞ", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # I and J are one letter in the printed index (Jagdberg, Jauer, Ibbs,
    # Ibsa, Jechaburg, ...), so they collate - and group - together as i
    return re.sub(r"[^a-z0-9]", "", text.lower()).replace("j", "i")


def sort_keys(place):
    """Possible filing keys for a headword, most likely first.

    'Altaich (Altach)'      -> altaich        (trailing gloss dropped)
    '(Gross-) Enzersdorf'   -> grossenzersdorf, enzersdorf
    '(Kl.) Zacken'          -> klzacken, zacken
    'de Sanctogallo'        -> sanctogallo
    """
    place = place or ""
    variants = []
    # 1. drop a bracketed gloss after a space, keep in-word brackets' letters
    v1 = re.sub(r"\s+\([^)]*\)", " ", strip_particles(place))
    variants.append(v1.replace("(", "").replace(")", ""))
    # 2. keep everything, just lose the brackets
    variants.append(strip_particles(place).replace("(", "").replace(")", ""))
    # 3. drop every bracketed part
    variants.append(strip_particles(re.sub(r"\([^)]*\)", " ", place)))
    keys = []
    for v in variants:
        k = fold(strip_particles(v))
        if k and k not in keys:
            keys.append(k)
    return keys or [""]


def primary_key(place):
    return sort_keys(place)[0]


# ---------------------------------------------------------------- input

class Entry:
    __slots__ = ("el", "source", "base", "suffix", "place", "assigned")

    def __init__(self, el, source):
        self.el = el
        self.source = source
        ort_id = el.get("id", "")
        base, _, suffix = ort_id.partition("-")
        self.base = int(base)
        self.suffix = int(suffix) if suffix else 0
        self.place = (el.findtext("place") or "").strip()
        self.assigned = el.get("id_source") == "assigned"

    @property
    def id(self):
        return self.el.get("id")


def read_entries(path, source):
    root = ET.parse(path).getroot()
    return root, [Entry(o, source) for o in root.iter("ort")]


# ---------------------------------------------------------------- split ids

def field(entry, tag):
    return (entry.el.findtext(tag) or "").strip()


def same_place(a, b):
    """Two rows are the same headword when the place name and the diocese
    match. The name variant only decides when one row has no diocese.

    Born / Colon. dioc. and Born / Magunt. dioc. are two places. A shared
    variant does NOT join two dioceses: Ebersbach (Eberspach) in Bamberg.
    and Misn. dioc., Gernrode, Kirchheim, Marbach, Raab and Reichenbach all
    have one unused number directly below them - one per extra diocese -
    so the volume printed them as separate headwords."""
    if field(a, "place") != field(b, "place"):
        return False
    da, db = field(a, "dioc"), field(b, "dioc")
    if da == db:
        return True
    if da and db:
        return False
    variant = field(a, "name_variant")
    return bool(variant) and variant == field(b, "name_variant")


def split_shared_ids(real):
    """Gives each place its own running number where the mapping merged
    consecutive same-named places onto one id.

    The id mapping matched on the place name only, so two different places
    called Altdorf printed one after the other both got 10300047, and the
    first one's number, 10300046, was left unused. Rows sharing an id are
    grouped with same_place(); if there are k groups and the k-1 numbers
    directly below the id are unused, the groups take those numbers in the
    order they are printed and the last group keeps the id:

        10300047-1  Altdorf  Argent. dioc.   ->  10300046-1
        10300047-2  Altdorf  Ratisp. dioc.   ->  10300047-1

    Row suffixes are renumbered from 1 inside each new id. Changes the
    entries in place and returns report rows."""
    by_base = defaultdict(list)
    for e in real:
        by_base[e.base].append(e)
    used = set(by_base)
    report = []

    for base in sorted(by_base):
        rows = sorted(by_base[base], key=lambda e: (e.suffix, e.source))
        groups = []
        for e in rows:
            for g in groups:
                if any(same_place(e, x) for x in g):
                    g.append(e)
                    break
            else:
                groups.append([e])
        if len(groups) < 2:
            continue

        need = len(groups) - 1
        free = []
        n = base - 1
        while len(free) < need and n > 0 and n not in used:
            free.insert(0, n)
            n -= 1
        if len(free) < need:
            for g in groups:
                report.append(_split_row(g[0], g[0].id, "",
                                         f"{len(groups)} places share this id but only "
                                         f"{len(free)} unused number(s) directly below "
                                         f"- left unchanged, check the volume"))
            continue

        for new_base, g in zip(free + [base], groups):
            used.add(new_base)
            for k, e in enumerate(g, 1):
                old = e.id
                e.base, e.suffix = new_base, k
                e.el.set("id", f"{new_base}-{k}")
                report.append(_split_row(e, old, e.id, "split from shared id"
                                         if new_base != base else "kept id, renumbered"))
    return report


# ---------------------------------------------------------------- lemma ids

def lemma_numbers(text):
    return [int(n) for n in re.findall(r"\d+", text or "")]


def convert_lemma_ids(entries, base=LEMMA_ID_BASE):
    """'107, 161, 179, 256' -> '10300107, 10300161, 10300179, 10300256'.

    Only the numbers change; separators and brackets stay as printed, so
    '(233 345)' becomes '(10300233 10300345)'. Returns the number of values
    converted. Refuses a number that would not fit below the next volume's
    block (base + 100000)."""
    count = 0
    for e in entries:
        el = e.el.find("lemma_id")
        if el is None or not el.text:
            continue
        for n in lemma_numbers(el.text):
            if n >= 100000:
                raise ValueError(f"{e.id}: lemma id {n} is too large for {base}")
            count += 1
        el.text = re.sub(r"\d+", lambda m: str(base + int(m.group())), el.text)
    return count


def _split_row(e, old, new, note):
    return {"old_id": old, "new_id": new, "place": field(e, "place"),
            "dioc": field(e, "dioc"), "name_variant": field(e, "name_variant"),
            "source": e.source, "note": note}


# ---------------------------------------------------------------- placing

def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def find_slot(keys, seq):
    """seq: real headwords in id order as (base, key, place).

    Returns (slot, key_used): the entry goes between seq[slot-1] and
    seq[slot]. Prefers slots with an unused running number between the
    neighbours, then the most likely reading of the name, then the slot
    whose neighbours share the longest prefix with the key."""
    best = None
    for rank, key in enumerate(keys):
        for i in range(len(seq) + 1):
            prev_ok = i == 0 or seq[i - 1][1] <= key
            next_ok = i == len(seq) or key < seq[i][1]
            if not (prev_ok and next_ok):
                continue
            lo = seq[i - 1][0] if i else None
            hi = seq[i][0] if i < len(seq) else None
            has_gap = lo is not None and hi is not None and hi - lo > 1
            closeness = max(common_prefix(key, seq[i - 1][1]) if i else 0,
                            common_prefix(key, seq[i][1]) if i < len(seq) else 0)
            score = (has_gap, -rank, closeness)
            if best is None or score > best[0]:
                best = (score, i, key)
    if best is None:          # cannot happen: some slot always satisfies both
        return len(seq), keys[0]
    return best[1], best[2]


def place_assigned(real, assigned):
    """Returns the merged list of entries and the report rows."""
    # real headwords in printed order
    seq = []
    for e in real:
        if not seq or seq[-1][0] != e.base:
            seq.append((e.base, primary_key(e.place), e.place))

    # one placement per assigned headword (rows of a place share a base)
    groups = defaultdict(list)
    for e in assigned:
        groups[e.base].append(e)

    by_slot = defaultdict(list)
    group_info = {}
    for base, rows in groups.items():
        rows.sort(key=lambda e: e.suffix)
        slot, key = find_slot(sort_keys(rows[0].place), seq)
        by_slot[slot].append(base)
        group_info[base] = {"slot": slot, "key": key, "rows": rows}

    # suggested ids: the unused numbers in each slot, given out in
    # alphabetical order when they are exactly enough
    report = []
    for slot, bases in by_slot.items():
        bases.sort(key=lambda b: (group_info[b]["key"], b))
        lo = seq[slot - 1][0] if slot else None
        hi = seq[slot][0] if slot < len(seq) else None
        free = list(range(lo + 1, hi)) if lo is not None and hi is not None else []
        for n, base in enumerate(bases):
            info = group_info[base]
            if free and len(free) == len(bases):
                info["suggested"] = str(free[n])
                note = "unused number in the slot"
            elif not free:
                info["suggested"] = ""
                note = "no unused number between the neighbours - check the volume"
            else:
                info["suggested"] = ""
                note = (f"{len(bases)} assigned place(s) for {len(free)} unused "
                        f"number(s) here - check the volume")
            report.append({
                "assigned_id": info["rows"][0].id.split("-")[0],
                "place": info["rows"][0].place,
                "rows": len(info["rows"]),
                "source": info["rows"][0].source,
                "sort_key": info["key"],
                "after_id": lo or "",
                "after_place": seq[slot - 1][2] if slot else "",
                "before_id": hi or "",
                "before_place": seq[slot][2] if slot < len(seq) else "",
                "unused_numbers_in_slot": " ".join(map(str, free)),
                "id_suggested": info["suggested"],
                "note": note,
            })

    # build the merged order
    merged = []
    letter_of = {}
    real_by_base = defaultdict(list)
    for e in real:
        real_by_base[e.base].append(e)
    for i in range(len(seq) + 1):
        for base in by_slot.get(i, []):
            info = group_info[base]
            for e in info["rows"]:
                merged.append(e)
                letter_of[id(e)] = info["key"][:1]
        if i < len(seq):
            for e in real_by_base[seq[i][0]]:
                merged.append(e)
                letter_of[id(e)] = seq[i][1][:1]

    report.sort(key=lambda r: (int(r["after_id"] or 0), r["sort_key"]))
    return merged, letter_of, group_info, report, seq


def index_letters(merged, letter_of):
    """Letter group of each entry, in merged order. A new group starts only
    when the next LETTER_LOOKAHEAD entries agree on the new letter, so a
    headword filed out of line stays in the group around it."""
    letters = [letter_of[id(e)] or "?" for e in merged]
    out = []
    current = None
    for i, ch in enumerate(letters):
        if current is None:
            current = ch
        elif ch != current:
            ahead = letters[i:i + LETTER_LOOKAHEAD]
            if all(c == ch for c in ahead):
                current = ch
        out.append(current)
    return out


# ---------------------------------------------------------------- output

def build_tree(merged, letters, volume):
    root = ET.Element("ortsverzeichnis", {"volume": volume})
    idx = None
    for e, ch in zip(merged, letters):
        if idx is None or idx.get("char") != ch:
            idx = ET.SubElement(root, "index", {"type": "orte", "char": ch})
        idx.append(e.el)
    ET.indent(root, space="\t")
    return root


def lemma_count(root):
    return sum(len([c for c in re.split(r"[,;]", el.text or "") if c.strip()])
               for el in root.iter("lemma_id"))


def verify(path, inputs, want_ids):
    """want_ids: every entry's id after split_shared_ids()."""
    root = ET.parse(path).getroot()
    problems = []
    ids = [o.get("id") for o in root.iter("ort")]
    if len(ids) != len(want_ids):
        problems.append(f"{len(want_ids)} <ort> in the inputs but {len(ids)} merged")
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"id used more than once: {dupes[:5]}")
    missing = set(want_ids) - set(ids)
    if missing:
        problems.append(f"{len(missing)} id(s) lost: {sorted(missing)[:5]}")
    for tag in ("place", "reference"):
        want = sum(len(r.findall(f".//{tag}")) for r in inputs)
        got = len(root.findall(f".//{tag}"))
        if want != got:
            problems.append(f"{want} <{tag}> in the inputs but {got} merged")
    want = sum(lemma_count(r) for r in inputs)
    got = lemma_count(root)
    if want != got:
        problems.append(f"{want} column numbers in the inputs but {got} merged")
    chars = [i.get("char") for i in root.findall("index")]
    repeated = [c for c, n in Counter(chars).items() if n > 1]
    if repeated:
        problems.append(f"letter group(s) split in two: {repeated}")
    return problems


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--main", default=IN_MAIN)
    ap.add_argument("--references", default=IN_REFERENCES)
    ap.add_argument("--out", default=OUT_XML)
    ap.add_argument("--report", default=OUT_REPORT)
    ap.add_argument("--split-report", default=OUT_SPLIT_REPORT)
    ap.add_argument("--no-lemma-prefix", action="store_true",
                    help="keep <lemma_id> as plain column numbers")
    ap.add_argument("--no-suggest", action="store_true",
                    help="do not add id_suggested to assigned entries")
    args = ap.parse_args()

    root_m, main_entries = read_entries(args.main, "main")
    root_r, ref_entries = read_entries(args.references, "references")
    entries = main_entries + ref_entries

    real = [e for e in entries if not e.assigned]
    assigned = [e for e in entries if e.assigned]

    # a running number should belong to one file and one place only
    files_of, places_of = defaultdict(set), defaultdict(set)
    for e in real:
        files_of[e.base].add(e.source)
        places_of[e.base].add(e.place)
    shared = sorted(b for b, s in files_of.items() if len(s) > 1)
    multi = sorted(b for b, p in places_of.items() if len(p) > 1)

    # before anything is placed: same-named places that share one id get
    # their own numbers back, so those gaps are no longer free for others
    split_report = split_shared_ids(real)
    split_ids = {r["new_id"].split("-")[0] for r in split_report
                 if r["note"] == "split from shared id"}
    split_failed = {r["old_id"].split("-")[0] for r in split_report if not r["new_id"]}
    with open(args.split_report, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["old_id", "new_id", "place", "dioc",
                                          "name_variant", "source", "note"])
        w.writeheader()
        w.writerows(split_report)

    # column numbers -> 8-digit lemma ids (originals kept for the check)
    lemma_before = sorted(n for e in entries
                          for n in lemma_numbers(e.el.findtext("lemma_id")))
    lemma_converted = 0 if args.no_lemma_prefix else convert_lemma_ids(entries)
    lemma_base = 0 if args.no_lemma_prefix else LEMMA_ID_BASE

    real.sort(key=lambda e: (e.base, e.suffix, e.source))
    merged, letter_of, group_info, report, seq = place_assigned(real, assigned)

    if not args.no_suggest:
        for info in group_info.values():
            if info.get("suggested"):
                for e in info["rows"]:
                    e.el.set("id_suggested", info["suggested"])

    letters = index_letters(merged, letter_of)
    root = build_tree(merged, letters, root_m.get("volume", "3"))
    ET.ElementTree(root).write(args.out, encoding="utf-8", xml_declaration=True)

    with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0]) if report else ["note"])
        w.writeheader()
        w.writerows(report)

    # how alphabetical is the printed order under the learned key?
    inversions = sum(1 for a, b in zip(seq, seq[1:]) if b[1] < a[1])
    numbers = [b for b, _, _ in seq]
    unused = [n for n in range(numbers[0], numbers[-1] + 1)
              if n not in set(numbers)]
    suggested = sum(1 for i in group_info.values() if i.get("suggested"))

    print(f"<ort> in {args.main:<38}: {len(main_entries)}")
    print(f"<ort> in {args.references:<38}: {len(ref_entries)}")
    print(f"Headwords with a real id              : {len(seq)} "
          f"({numbers[0]} .. {numbers[-1]}, {len(unused)} numbers unused)")
    print(f"Headwords out of alphabetical order   : {inversions} "
          f"(printed order kept, only used to place assigned entries)")
    print(f"Assigned headwords placed by name     : {len(group_info)} "
          f"({len(assigned)} rows), id_suggested for {suggested}")
    print(f"Shared ids split into separate places : {len(split_ids)} new id(s) "
          f"-> {args.split_report}")
    if split_failed:
        print(f"Shared ids NOT split (no free number) : {sorted(split_failed)}")
    print(f"Lemma ids converted to 8 digits       : {lemma_converted}"
          + (" (--no-lemma-prefix)" if args.no_lemma_prefix else
             f" ({lemma_before[0]} -> {lemma_before[0] + LEMMA_ID_BASE})"))
    print(f"Letter groups                         : {len(root.findall('index'))}")
    if shared:
        print(f"\nWARNING: running number used in both files: {shared[:10]}")
    if multi:
        print(f"\nWARNING: running number used for different places: {multi[:10]}")

    bad = verify(args.out, [root_m, root_r], [e.id for e in entries])
    lemma_after = sorted(n for el in ET.parse(args.out).getroot().iter("lemma_id")
                         for n in lemma_numbers(el.text))
    if lemma_after != [n + lemma_base for n in lemma_before]:
        bad.append("lemma ids in the merged file are not the input column "
                   f"numbers + {lemma_base}")
    print("\nChecks                                : "
          + ("all passed" if not bad else f"{len(bad)} FAILED"))
    for b in bad:
        print(f"  {b}")
    print(f"\nWrote {args.out}")
    print(f"Wrote {args.report}  ({len(report)} assigned headwords to check)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
