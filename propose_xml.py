"""
build_orte_vol3_xml.py

Turns the volume 3 place index CSV into XML.

    python build_orte_vol3_xml.py
    python build_orte_vol3_xml.py ortsverzeichnis_vol3_no_references_mapped.csv
    python build_orte_vol3_xml.py --preview 5      # print the first 5, write nothing
    python propose_xml.py --references             # build the references-only XML


WHAT ONE XML ENTRY IS
---------------------
One CSV row. The CSV is already exploded one row per institution-and-office
pair, so a place with several institutions, each with several offices, arrives
as several rows:

    10300001  Aachen  ...  eccl. s. Adalberti  prepos.  239
    10300001  Aachen  ...  eccl. s. Adalberti  can.     239
    10300001  Aachen  ...  eccl. s. Marie      (none)   54
    ...

Each becomes its own <ort>, and the ort id carries a suffix so the rows stay
distinguishable and no column number is merged into a neighbour:

    10300001-1, 10300001-2, 10300001-3, ...

The suffix is positional within the ort_id, in CSV order. Aachen has 18 rows,
so 10300001-1 .. 10300001-18. Because the suffix depends on row ORDER, do not
re-sort the CSV between runs or the ids will move. SUFFIX_FOR_SINGLETONS below
controls whether a place with only one row gets "-1" or stays bare.


ENTRIES WITH NO ort_id
----------------------
27 rows have an empty ort_id: the matching entry in the old XML was malformed,
so nothing could be mapped onto it.

They are NOT given "the previous ort_id + 1". The gap above each of them looks
free in this file, but the place index was split into two CSVs - the entries
with references went to the other one - so a number that is unused HERE may
well be in use THERE. Guessing into those gaps would hand the same id to two
different places once the files are put back together.

Instead each such place is given an id from a reserved block that nothing else
can reach:

    NEW_ID_BASE = 10390001, so 10390001, 10390002, ... in file order

The printed sequence ends at 10302639, so the block is above anything either
CSV can hold. The script checks the block is clear of every id in this file
before using it, and NEW_ID_BASE is a constant you can move if the reference
file turns out to reach higher.

Rows of the SAME place share one id (Frauenchiemsee has two rows, so
10390003-1 and 10390003-2). Every such entry is marked in the XML with
id_source="assigned" and listed in OUT_UNMAPPED with the place it belongs to,
so the real number can be filled in later from the volume.


TAGS
----
One element per CSV column, in CSV order:

    <place>         Place
    <name_variant>  Name Variant, verbatim - several variants stay one
                    comma-separated string. XML names cannot contain a space,
                    so the tag is name_variant, not "name variant".
    <dioc>          Diocese
    <institution>   Institution
    <office>        Office
    <lemma_id>      Column_num, verbatim

Empty fields are omitted by default. Set KEEP_EMPTY = True to emit them as
empty elements instead, if the consumer wants a fixed element list.


CHECKS
------
At the end the script verifies that the XML holds exactly as many column
numbers inside <lemma_id> as the CSV has, that every row produced one <ort>,
and that no id is used twice. It re-parses its own output to do this, so a
malformed file is caught here and not downstream.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import pandas as pd

IN_DEFAULT = "ortsverzeichnis_vol3_no_references_mapped.csv"
OUT_XML = "ortsverzeichnis_vol3.xml"
OUT_UNMAPPED = "ortsverzeichnis_vol3_unmapped.csv"

# a place with a single row: "10300042-1", or plain "10300042"?
SUFFIX_FOR_SINGLETONS = True
# emit empty elements for blank fields instead of leaving them out
KEEP_EMPTY = False
# first id for a place the old XML could not supply one for. Must sit above
# every id in BOTH halves of the split index - see the note above.
NEW_ID_BASE = 10390001
IN_REFERENCES_DEFAULT = "ortsverzeichnis_vol3_references_only_mapped_fixed.csv"
OUT_REFERENCES_XML = "ortsverzeichnis_vol3_references.xml"
OUT_REFERENCES_UNMAPPED = "ortsverzeichnis_vol3_references_unmapped.csv"
NEW_REFERENCE_ID_BASE = 10391001

COLS = ["ort_id", "Place", "Name Variant", "Diocese",
        "Institution", "Office", "Column_num"]


# ---------------------------------------------------------------- ids

def assign_missing_ids(df, new_id_base=NEW_ID_BASE):
    """Gives every blank ort_id an id from the reserved block.

    Returns (ids, report_rows, problems). ids is a list parallel to df: the
    ort_id to use for each row.

    The block is NOT derived from the surrounding numbers. A gap in this file
    is not evidence the number is free, because the other half of the index -
    the entries with references - draws on the same sequence.
    """
    ids = df["ort_id"].tolist()
    real = {i for i in ids if i}
    out = list(ids)
    problems = []
    report = []

    blanks = [i for i, v in enumerate(ids) if not v]
    if not blanks:
        return out, report, problems

    # one id per distinct place, in the order the places first appear
    places = list(dict.fromkeys(df["Place"].iloc[j] for j in blanks))
    assigned = {}
    for k, place in enumerate(places):
        cand = str(new_id_base + k)
        if cand in real:
            problems.append(
                f"{place!r}: reserved id {cand} is already used in this file - "
                f"raise NEW_ID_BASE above {max(int(i) for i in real)}")
            continue
        assigned[place] = cand
        real.add(cand)

    for j in blanks:
        place = df["Place"].iloc[j]
        cand = assigned.get(place)
        if cand:
            out[j] = cand
        neighbours = (next((ids[x] for x in range(j - 1, -1, -1) if ids[x]), ""),
                      next((ids[x] for x in range(j + 1, len(ids)) if ids[x]), ""))
        report.append({**{c: df[c].iloc[j] for c in COLS},
                       "assigned_ort_id": cand or "",
                       "id_source": "reserved block" if cand else "NOT ASSIGNED",
                       "printed_between": f"{neighbours[0]} .. {neighbours[1]}"})
    return out, report, problems


def add_suffixes(ids):
    """10300001 -> 10300001-1, -2, -3 ... in file order."""
    total = Counter(i for i in ids if i)
    seen = defaultdict(int)
    out = []
    for i in ids:
        if not i:
            out.append("")
            continue
        seen[i] += 1
        if total[i] == 1 and not SUFFIX_FOR_SINGLETONS:
            out.append(i)
        else:
            out.append(f"{i}-{seen[i]}")
    return out


# ---------------------------------------------------------------- xml

def index_char(place):
    """The letter the entry files under: first letter, ignoring '(', spaces
    and the like. '(Gross-) Enzersdorf' -> 'g'.

    NOTE this is the first letter AS PRINTED. The printed index may file a
    compound under its main word instead ('zum Bruche' under B); check a few
    against the volume before relying on the grouping.
    """
    m = re.search(r"[A-Za-zÀ-ÿ]", str(place))
    return m.group(0).lower() if m else "?"


def columns_of(cell):
    """'107, 161, 179, 256' -> ['107', '161', '179', '256']"""
    return [c.strip() for c in re.split(r"[,;]", str(cell)) if c.strip()]


def sub(parent, tag, text):
    if text or KEEP_EMPTY:
        ET.SubElement(parent, tag).text = text or None
    return parent


def build_ort(row, ort_id, assigned):
    el = ET.Element("ort", {"id": ort_id})
    if assigned:
        el.set("id_source", "assigned")

    sub(el, "place", row["Place"].strip())
    # several variants stay one comma-separated string, as in the CSV
    sub(el, "name_variant", row["Name Variant"].strip())
    sub(el, "dioc", row["Diocese"].strip())
    sub(el, "institution", row["Institution"].strip())
    sub(el, "office", row["Office"].strip())
    sub(el, "lemma_id", ", ".join(columns_of(row["Column_num"])))
    return el


def comma_values(cell):
    """Splits a comma-separated place or reference field into XML values."""
    return [value.strip() for value in str(cell).split(",") if value.strip()]


def build_reference_ort(row, ort_id, assigned):
    el = ET.Element("ort", {"id": ort_id})
    if assigned:
        el.set("id_source", "assigned")

    for place in comma_values(row["Place"]):
        sub(el, "place", place)
    for reference in comma_values(row["Reference"]):
        sub(el, "reference", reference)
    return el


def build_reference_tree(df, full_ids, assigned_rows):
    root = ET.Element("ortsverzeichnis", {"volume": "3"})
    by_char = defaultdict(list)
    order = []
    for pos in range(len(df)):
        places = comma_values(df["Place"].iloc[pos])
        ch = index_char(places[0] if places else "")
        if ch not in by_char:
            order.append(ch)
        by_char[ch].append(pos)

    for ch in order:
        idx = ET.SubElement(root, "index", {"type": "orte", "char": ch})
        for pos in by_char[ch]:
            if full_ids[pos]:
                idx.append(build_reference_ort(df.iloc[pos], full_ids[pos], pos in assigned_rows))
    return root


def build_tree(df, full_ids, assigned_rows):
    root = ET.Element("ortsverzeichnis", {"volume": "3"})
    by_char = defaultdict(list)
    order = []
    for pos in range(len(df)):
        ch = index_char(df["Place"].iloc[pos])
        if ch not in by_char:
            order.append(ch)
        by_char[ch].append(pos)

    for ch in order:
        idx = ET.SubElement(root, "index", {"type": "orte", "char": ch})
        for pos in by_char[ch]:
            if not full_ids[pos]:
                continue          # unassigned: it is in the unmapped CSV only
            idx.append(build_ort(df.iloc[pos], full_ids[pos], pos in assigned_rows))
    return root


def indent(el, level=0):
    pad = "\n" + "\t" * level
    # an element with text of its own is mixed content (<name>Aachen <ka/>...)
    # - indenting inside it would add whitespace that belongs to the text
    if (el.text or "").strip():
        if level and not (el.tail or "").strip():
            el.tail = pad
        return
    if len(el):
        if not (el.text or "").strip():
            el.text = pad + "\t"
        for child in el:
            indent(child, level + 1)
        if not (el[-1].tail or "").strip():
            el[-1].tail = pad
    if level and not (el.tail or "").strip():
        el.tail = pad


# ---------------------------------------------------------------- checks

def verify(path, df, full_ids):
    """Re-reads the written file and compares it with the CSV."""
    root = ET.parse(path).getroot()
    orts = root.findall(".//ort")
    problems = []

    expected_rows = sum(1 for i in full_ids if i)
    if len(orts) != expected_rows:
        problems.append(f"{expected_rows} rows to write but {len(orts)} <ort> in the file")

    want = sum(len(columns_of(c)) for c in df["Column_num"])
    got = sum(len(columns_of(e.text or "")) for e in root.findall(".//lemma_id"))
    if want != got:
        problems.append(f"{want} column numbers in the CSV but {got} in <lemma_id>")

    ids = [o.get("id") for o in orts]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"id used more than once: {dupes[:5]}")

    bare = {i.rsplit("-", 1)[0] for i in ids}
    csv_bare = {i for i in full_ids if i}
    csv_bare = {i.rsplit("-", 1)[0] for i in csv_bare}
    if bare != csv_bare:
        problems.append(f"{len(csv_bare - bare)} ort_id(s) in the CSV are not in the file")
    return problems


def verify_references(path, df, full_ids):
    """Checks reference row count, values, and ID uniqueness in the XML."""
    root = ET.parse(path).getroot()
    orts = root.findall(".//ort")
    problems = []

    expected_rows = sum(1 for ort_id in full_ids if ort_id)
    if len(orts) != expected_rows:
        problems.append(f"{expected_rows} rows to write but {len(orts)} <ort> in the file")

    want_places = sum(len(comma_values(value)) for value in df["Place"])
    got_places = len(root.findall(".//place"))
    if want_places != got_places:
        problems.append(f"{want_places} places in the CSV but {got_places} <place> tags")

    want_references = sum(len(comma_values(value)) for value in df["Reference"])
    got_references = len(root.findall(".//reference"))
    if want_references != got_references:
        problems.append(
            f"{want_references} references in the CSV but {got_references} <reference> tags"
        )

    ids = [ort.get("id") for ort in orts]
    dupes = [ort_id for ort_id, count in Counter(ids).items() if count > 1]
    if dupes:
        problems.append(f"id used more than once: {dupes[:5]}")

    bare = {ort_id.rsplit("-", 1)[0] for ort_id in ids}
    csv_bare = {ort_id.rsplit("-", 1)[0] for ort_id in full_ids if ort_id}
    if bare != csv_bare:
        problems.append(f"{len(csv_bare - bare)} ort_id(s) in the CSV are not in the file")
    return problems


# ---------------------------------------------------------------- main

def build_references_output(path, preview=0):
    if not os.path.exists(path):
        print(f"Not found: {path}")
        sys.exit(1)

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    for column in ("ort_id", "Place", "Reference"):
        if column not in df.columns:
            print(f"The CSV has no {column!r} column. Found: {list(df.columns)}")
            sys.exit(1)

    base_ids, report, problems = assign_missing_ids(
        df, new_id_base=NEW_REFERENCE_ID_BASE
    )
    assigned_rows = {
        pos
        for pos, (original, assigned) in enumerate(zip(df["ort_id"], base_ids))
        if not original and assigned
    }
    full_ids = add_suffixes(base_ids)

    if preview:
        for pos in range(min(preview, len(df))):
            element = build_reference_ort(df.iloc[pos], full_ids[pos], pos in assigned_rows)
            indent(element)
            print(ET.tostring(element, encoding="unicode"))
        return

    root = build_reference_tree(df, full_ids, assigned_rows)
    indent(root)
    ET.ElementTree(root).write(
        OUT_REFERENCES_XML, encoding="utf-8", xml_declaration=True
    )

    if report:
        pd.DataFrame(report).to_csv(
            OUT_REFERENCES_UNMAPPED, index=False, encoding="utf-8-sig"
        )

    n_places = len({ort_id for ort_id in base_ids if ort_id})
    print(f"CSV rows            : {len(df)}")
    print(f"Distinct places     : {n_places}")
    print(f"<ort> written       : {sum(1 for ort_id in full_ids if ort_id)}")
    print(f"Ids assigned        : {len(assigned_rows)} rows "
          f"({len({base_ids[pos] for pos in assigned_rows})} places)")
    if problems:
        print(f"\n{len(problems)} id problem(s) - those rows were NOT written to the XML:")
        for problem in problems:
            print(f"  {problem}")
    bad = verify_references(OUT_REFERENCES_XML, df, full_ids)
    print("\nChecks              : " + ("all passed" if not bad else f"{len(bad)} FAILED"))
    for problem in bad:
        print(f"  {problem}")
    print(f"\nWrote {OUT_REFERENCES_XML}")
    if report:
        print(f"Wrote {OUT_REFERENCES_UNMAPPED}  ({len(report)} rows to check against the volume)")


def main():
    args = list(sys.argv[1:])
    references_mode = "--references" in args
    if references_mode:
        args.remove("--references")

    preview = 0
    if "--preview" in args:
        preview_index = args.index("--preview")
        if preview_index + 1 < len(args) and not args[preview_index + 1].startswith("--"):
            preview = int(args[preview_index + 1])
            del args[preview_index:preview_index + 2]
        else:
            preview = 5
            del args[preview_index]

    default_path = IN_REFERENCES_DEFAULT if references_mode else IN_DEFAULT
    path = args[0] if args else default_path
    if not os.path.exists(path):
        print(f"Not found: {path}")
        sys.exit(1)

    if references_mode:
        build_references_output(path, preview=preview)
        return

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    for c in COLS:
        if c not in df.columns:
            print(f"The CSV has no {c!r} column. Found: {list(df.columns)}")
            sys.exit(1)

    base_ids, report, problems = assign_missing_ids(df)
    assigned_rows = {i for i, (a, b) in enumerate(zip(df["ort_id"], base_ids)) if not a and b}
    full_ids = add_suffixes(base_ids)

    if preview:
        for pos in range(min(preview, len(df))):
            el = build_ort(df.iloc[pos], full_ids[pos], pos in assigned_rows)
            indent(el)
            print(ET.tostring(el, encoding="unicode"))
        return

    root = build_tree(df, full_ids, assigned_rows)
    indent(root)
    ET.ElementTree(root).write(OUT_XML, encoding="utf-8", xml_declaration=True)

    if report:
        pd.DataFrame(report).to_csv(OUT_UNMAPPED, index=False, encoding="utf-8-sig")

    n_places = len({i for i in base_ids if i})
    print(f"CSV rows            : {len(df)}")
    print(f"Distinct places     : {n_places}")
    print(f"<ort> written       : {sum(1 for i in full_ids if i)}")
    print(f"Index letters       : {len(root.findall('index'))}")
    print(f"Ids assigned        : {len(assigned_rows)} rows "
          f"({len({base_ids[i] for i in assigned_rows})} places)")
    if problems:
        print(f"\n{len(problems)} id problem(s) - those rows were NOT written to the XML:")
        for p in problems:
            print(f"  {p}")
    bad = verify(OUT_XML, df, full_ids)
    print("\nChecks              : " + ("all passed" if not bad else f"{len(bad)} FAILED"))
    for b in bad:
        print(f"  {b}")
    print(f"\nWrote {OUT_XML}")
    if report:
        print(f"Wrote {OUT_UNMAPPED}  ({len(report)} rows to check against the volume)")


if __name__ == "__main__":
    main()