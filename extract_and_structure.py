#!/usr/bin/env python3
"""
extract_and_structure.py

End-to-end extraction and structuring pipeline for Ortsverzeichnis Vol. 3:
  1. Parses raw headwords, bracketed name variants, dioceses, and sub-entries.
  2. Merges orphan parish ('par.') records into their respective institutions.
  3. Applies structured anomaly overrides (e.g. Pisa, Conneux, Kurzelow, Toggenburg, Greifswald, Amsterdam).
  4. Removes lone alphabet divider rows.
  5. Separates cross-reference entries from substantive entries.
  6. Audits and exports any records lacking column numbers.
"""

import os
import re
from pathlib import Path
import pandas as pd


# ==============================================================================
# 1. TEXT ENCODING & FORMATTING HELPERS
# ==============================================================================

def fix_mojibake_str(val):
    """
    Repairs double-encoded UTF-8 / Latin-1 string sequences (e.g. 'Ã¤' -> 'ä').
    """
    if isinstance(val, str):
        try:
            return val.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return val
    return val


def format_column_numbers(num_string):
    """
    Standardizes page/column citation numbers into comma-separated strings.
    """
    if not num_string:
        return ""
    tokens = re.findall(
        r"\(\s*\d+(?:[\s–\-]\d+)*\s*\)|\d+(?:[–\-]\d+)?", str(num_string)
    )
    cleaned_tokens = [re.sub(r"\s+", " ", t.strip()) for t in tokens]
    return ", ".join(cleaned_tokens)


# ==============================================================================
# 2. DICTIONARY & PREFIX REGISTRIES
# ==============================================================================

INSTITUTION_PREFIXES = (
    "eccl.",
    "par. eccl.",
    "(par.) eccl.",
    "capel.",
    "nova capel.",
    "mon.",
    "dom.",
    "hosp.",
    "parochia",
    "studium",
    "abbatia",
    "dominus terre",
)

PERSON_OR_ROLE_PREFIXES = (
    "ep.",
    "aep.",
    "vic.",
    "vic. gen.",
    "chorep.",
    "chorepisc.",
    "offic.",
    "presb.",
    "subdiacon.",
    "cler.",
    "fr.",
    "scolar.",
    "provincia",
    "dioc.",
    "legatus",
    "nuntius",
    "collector",
    "subcollect.",
    "armig.",
    "mil.",
    "baron.",
    "domic.",
    "opid.",
    "laici",
    "civit.",
    "castella",
    "rex",
    "regina",
    "regnum",
    "plebanus",
    "pleban.",
    "marchio",
    "capellani",
    "flumen",
    "dux",
    "ducissa",
    "comes",
    "comites",
    "comitissa",
    "com.",
    "com. palat.",
    "dominium",
    "conv.",
    "provinc. concilium",
    "concilium",
    "doctor",
    "monach.",
    "curia aepisc.",
    "camerar.",
    "abbat.",
    "alt.",
    "advocatus",
    "advoc.",
    "archidiacon.",
    "archidiac.",
    "burgravi",
    "burgravius",
    "portus",
)


# ==============================================================================
# 3. RAW-LEVEL PATCHES
# ==============================================================================

def patch_special_raw_entries(text):
    # 1. Zürich inverted provost/dedication patch
    if "Zürich" in text and "prepos. ss. Felicis et Regule:" in text:
        text = text.replace(
            "prepos. ss. Felicis et Regule: 354 can.",
            "ss. Felicis et Regule: prepos. 354; can.",
        )

    # 2. Trier / Mainz / Bremen 'provincia: ...; <nums> (dom. s. Antoni...).'
    def replace_provincia_antonii(match):
        p_nums = match.group(1).strip()
        d_nums = match.group(2).strip()
        d_name = match.group(3).strip()
        return f"provincia {p_nums}. {d_name} {d_nums}."

    text = re.sub(
        r"provincia:?\s*([\d\s]+);\s*([\d\s]+)\s*\((dom\.[^)]+)\)\.?",
        replace_provincia_antonii,
        text,
    )

    # 3. Sachsen missing period between column citation 332 and dux
    if "Sachsen" in text and "332 dux" in text:
        text = text.replace("332 dux", "332. dux")

    # 4. Melk missing semicolon between custod. 224 and conv.
    if "Melk" in text and "custod. 224 conv." in text:
        text = text.replace("custod. 224 conv.", "custod. 224; conv.")

    # 5. Mainz missing delimiters and OCR glitches
    if "Mainz" in text:
        if "can. 254 397 capit. 320" in text:
            text = text.replace("can. 254 397 capit. 320", "can. 254 397; capit. 320")
        if "thesaurar. 119 can." in text:
            text = text.replace("thesaurar. 119 can.", "thesaurar. 119; can.")
        if "254 vic. 320" in text:
            text = text.replace("254 vic. 320", "254; vic. 320")
        if "sco. last." in text:
            text = text.replace("sco. last.", "scholast.")
        text = re.sub(
            r"(opid\.\s+[\d\s]+?376)\s+(laici\b)",
            r"\1. \2",
            text,
        )

    # 6. Hemelum missing semicolon between prepos. 178 and monach. 177
    if "Hemelum" in text and "prepos. 178 monach." in text:
        text = text.replace("prepos. 178 monach.", "prepos. 178; monach.")

    # 7. Heilsbronn missing semicolon between camerar. 266 and conv.
    if "Heilsbronn" in text and "camerar. 266 conv." in text:
        text = text.replace("camerar. 266 conv.", "camerar. 266; conv.")

    # 8. Freistadt (ob d. Ens) double-parenthesis handling
    text = re.sub(
        r"^Freistadt\s*\(ob d\. Ens\)\s*\((Freynstät)\s*Pata(?:v\.)?\s*dioc\.\)",
        r"Freistadt (ob d. Ens, \1 Patav. dioc.)",
        text,
        flags=re.IGNORECASE,
    )

    # 9. Frauenchiemsee missing digit (29 -> 293) and missing semicolon
    if "Frauenchiemsee" in text and "abbat. et conv. 29 alt. in eccl. 293" in text:
        text = text.replace(
            "abbat. et conv. 29 alt. in eccl. 293",
            "abbat. et conv. 293; alt. in eccl. 293",
        )

    # 10. Bremen missing semicolon between capit. (ending in 367) and vic.
    if "Bremen" in text and "293 367 vic." in text:
        text = text.replace("293 367 vic.", "293 367; vic.")

    # 11. Bamberg missing semicolon between prepos. 123 and decan. 123
    if "Bamberg" in text and "prepos. 123 decan. 123" in text:
        text = text.replace("prepos. 123 decan. 123", "prepos. 123; decan. 123")

    # 12. General fix for OCR bracket typos in diocese: '<Name>) dioc.)' -> '<Name>. dioc.)'
    text = re.sub(
        r"\b([A-ZÄÖÜ][a-zA-Zäöüß]+)\)\s*dioc\.\)",
        r"\1. dioc.)",
        text,
    )

    # 13. Altenburg missing semicolon after bare column citation 46
    if "Altenburg" in text and ": 46 prepos." in text:
        text = text.replace(": 46 prepos.", ": 46; prepos.")

    # 15. Merseburg missing full stop after 362 and missing semicolon
    if "Merseburg" in text:
        if "362 eccl.:" in text:
            text = text.replace("362 eccl.:", "362. eccl.:")
        if "vic. 274 alt. 53" in text:
            text = text.replace("vic. 274 alt. 53", "vic. 274; alt. 53")

    # 16. Nordhausen missing semicolon between scholast. 296 and can.
    if "Nordhausen" in text and "scholast. 296 can." in text:
        text = text.replace("scholast. 296 can.", "scholast. 296; can.")

    # 17. Balsamgau missing closing parenthesis after dioc
    if "Balsamgau" in text:
        text = re.sub(r"dioc\.?\s*(archidiacon\.)", r"dioc.) \1", text)

    # 18. Conneux missing closing parenthesis after dioc.
    if "Conneux" in text:
        text = re.sub(r"dioc\.?\s*(par\.\s*eccl\.)", r"dioc.) \1", text)

    # 19. Kurzelow missing closing parenthesis after dioc.
    if "Kurzelow" in text:
        text = re.sub(r"dioc\.?\s*(eccl\.:)", r"dioc.) \1", text)

    # 20. Trailing period on place names followed by role descriptors
    text = re.sub(r"\b([A-ZÄÖÜ][a-zA-Zäöüß]+)\.\s+(com\b|comes\b)", r"\1 \2", text)

    # 21. Dorpat missing full stop after 400 before eccl. and typo 'thesarar.'
    if "Dorpat" in text:
        if "400 eccl.:" in text:
            text = text.replace("400 eccl.:", "400. eccl.:")
        if "thesarar." in text:
            text = text.replace("thesarar.", "thesaurar.")

    # 22. Einsiedeln erroneous colon after column 79 instead of full stop
    if "Einsiedeln" in text and "79: mon." in text:
        text = text.replace("79: mon.", "79. mon.")

    # 23. Greifswald missing colon on (par.) eccl. s. Nicolai before sub-offices
    if "Greifswald" in text:
        text = re.sub(
            r"(\(par\.\)\s*eccl\.\s*s\.\s*Nicolai)\s+(\d+)\s*;\s*(prepos\.)",
            r"\1: \2; \3",
            text,
        )

    # 24. Amsterdam vernacular chapel prefix normalization
    if "Amsterdam" in text and "Nieuwe-Zijdskapel" in text:
        text = text.replace(
            "Nieuwe-Zijdskapel",
            "capel. Nieuwe-Zijdskapel",
        )

    return text


# ==============================================================================
# 4. STRUCTURED PARSING ENGINE
# ==============================================================================

def find_matching_close_paren(text, start_idx):
    depth = 0
    for i in range(start_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_place_header(text):
    text = text.strip()

    # Rule 1: Cross-Reference "Place v. Target."
    cross_match = re.match(r"^(.+?)\s+v\.\s+(.+)$", text, re.IGNORECASE)
    if cross_match:
        place = re.sub(r"\s+", " ", cross_match.group(1)).strip()
        ref = cross_match.group(2).strip().rstrip(".")
        return place, "", "", "", ref

    all_descriptors = sorted(
        list(INSTITUTION_PREFIXES) + list(PERSON_OR_ROLE_PREFIXES),
        key=len,
        reverse=True,
    )
    desc_pattern = (
        r"(?:(?<=\s)|(?<=\b))("
        + "|".join(re.escape(d) for d in all_descriptors)
        + r")"
    )

    place = ""
    name_variants = ""
    diocese = ""
    body = ""

    search_offset = 0
    leading_qualifier_match = re.match(r"^\([^)]+\)\s*", text)
    if leading_qualifier_match:
        search_offset = leading_qualifier_match.end()

    rel_paren_idx = text[search_offset:].find("(")
    first_paren_idx = (
        search_offset + rel_paren_idx if rel_paren_idx != -1 else -1
    )

    has_valid_head_paren = False

    if first_paren_idx != -1:
        prefix = text[:first_paren_idx].strip()
        has_no_digits = not bool(re.search(r"\d", prefix))
        has_no_descriptors = not bool(
            re.search(desc_pattern, prefix, re.IGNORECASE)
        )

        if has_no_digits and has_no_descriptors:
            has_valid_head_paren = True

    # Case A: Legitimate Headword Parenthesis
    if has_valid_head_paren:
        candidate_place = text[:first_paren_idx].strip().rstrip(".")
        place = re.sub(r"\s+", " ", candidate_place)

        matching_close_idx = find_matching_close_paren(text, first_paren_idx)

        if matching_close_idx != -1:
            bracket_content = text[
                first_paren_idx + 1 : matching_close_idx
            ].strip()
            body = text[matching_close_idx + 1 :].strip()
        else:
            bracket_content = text[first_paren_idx + 1 :].strip()
            body = ""

        special_editorial_dioc = re.search(
            r"([A-ZÄÖÜ][a-zA-Zäöüß]*(?:\.|\s+)\s*\(!\)\s*dioc\.?)$",
            bracket_content,
            re.IGNORECASE,
        )

        if special_editorial_dioc:
            diocese = special_editorial_dioc.group(1).strip()
            variants_raw = bracket_content[: special_editorial_dioc.start()]
            name_variants = re.sub(r"[,;\s]+$", "", variants_raw).strip()
        else:
            dioc_match = re.search(
                r"((?:\?\s*)?[A-ZÄÖÜ][a-zA-Zäöüß]*(?:-\s*[a-zA-Zäöüß]+)?(?:\.|\s+)\s*dioc\.?)$",
                bracket_content,
                re.IGNORECASE,
            )

            if dioc_match:
                diocese = dioc_match.group(1).strip()
                diocese = re.sub(r"-\s+", "-", diocese)
                diocese = re.sub(r"\.([a-zA-Z])", r". \1", diocese)
                if not diocese.endswith("."):
                    diocese += "."
                variants_raw = bracket_content[: dioc_match.start()].strip()
                name_variants = re.sub(r"[,;\s]+$", "", variants_raw).strip()
            else:
                diocese = ""
                name_variants = bracket_content.strip()

    # Case B: No Headword Parenthesis
    else:
        match_desc = re.search(desc_pattern, text)
        if match_desc and match_desc.start() > 0:
            place = text[: match_desc.start()].strip().rstrip(".")
            body = text[match_desc.start() :].strip()
        else:
            place = text.rstrip(".")
            body = ""
        place = re.sub(r"\s+", " ", place)
        name_variants = ""
        diocese = ""

    return place, name_variants, diocese, body, ""


def split_into_structural_blocks(body_text):
    raw_blocks = re.split(r"(?<=\d)\s*\.\s+(?=[a-z\(])", body_text.strip())
    blocks = []
    for blk in raw_blocks:
        blk = blk.strip().rstrip(".")
        if blk:
            blocks.append(blk)
    return blocks


def extract_office_and_numbers_with_parens(item):
    item = item.strip().rstrip(".")
    if not item:
        return "", ""

    if re.match(r"^[\d\s\.\–\-\(\)]+$", item):
        return "", format_column_numbers(item)

    num_match = re.search(r"^(.*?)(?:\s+([\d\(][\d\s\.\–\-\(\)]*))?$", item)
    if num_match:
        office_name = (num_match.group(1) or "").strip()
        page_nums = format_column_numbers(num_match.group(2) or "")
        return office_name, page_nums

    return item, ""


def parse_body_institutions_and_offices(body_text):
    if not body_text or not body_text.strip():
        return []

    cleaned_body = re.sub(r"(?<=\d)\.\s+(?=\d)", " ", body_text.strip())
    extracted_rows = []
    blocks = split_into_structural_blocks(cleaned_body)

    for block in blocks:
        if ":" in block:
            inst_part, offices_part = block.split(":", 1)
            inst_name = inst_part.strip()
            office_items = [
                o.strip() for o in offices_part.split(";") if o.strip()
            ]
            for item in office_items:
                office_name, page_nums = extract_office_and_numbers_with_parens(
                    item
                )
                extracted_rows.append({
                    "institution": inst_name,
                    "office": office_name,
                    "column_num": page_nums,
                })
        elif ";" in block:
            sub_items = [s.strip() for s in block.split(";") if s.strip()]
            for item in sub_items:
                office_name, page_nums = extract_office_and_numbers_with_parens(
                    item
                )
                is_institution = any(
                    office_name.startswith(prefix)
                    for prefix in INSTITUTION_PREFIXES
                )
                if is_institution:
                    extracted_rows.append({
                        "institution": office_name,
                        "office": "",
                        "column_num": page_nums,
                    })
                else:
                    extracted_rows.append({
                        "institution": "",
                        "office": office_name,
                        "column_num": page_nums,
                    })
        else:
            office_name, page_nums = extract_office_and_numbers_with_parens(
                block
            )
            is_institution = any(
                office_name.startswith(prefix)
                for prefix in INSTITUTION_PREFIXES
            )
            if is_institution:
                extracted_rows.append({
                    "institution": office_name,
                    "office": "",
                    "column_num": page_nums,
                })
            else:
                extracted_rows.append({
                    "institution": "",
                    "office": office_name,
                    "column_num": page_nums,
                })

    return extracted_rows


def merge_par_records(rows):
    """
    Consolidates orphan 'par.' office records into the subsequent institution.
    """
    cleaned_rows = []
    i = 0
    n = len(rows)

    while i < n:
        current_office = str(rows[i].get("Office", "")).strip().lower()

        if current_office in ("par", "par."):
            if i + 1 < n:
                next_inst = str(rows[i + 1].get("Institution", "")).strip()
                if next_inst and not next_inst.startswith("par."):
                    rows[i + 1]["Institution"] = f"par. {next_inst}"
                elif not next_inst:
                    rows[i + 1]["Institution"] = "par."
            i += 1
            continue

        cleaned_rows.append(rows[i])
        i += 1

    return cleaned_rows


# ==============================================================================
# 5. POST-EXTRACTION DATA REPAIR & AUDIT OVERRIDES
# ==============================================================================

def remove_alphabet_border_rows(df):
    """
    Removes stray single/double-letter alphabet header rows (e.g. 'D', 'H', 'I J', 'O').
    """
    is_letter_header = df["Place"].fillna("").astype(str).str.strip().str.match(
        r"^[A-Z](?:\s*[\-–\s]\s*[A-Z])?$", na=False
    )

    def is_col_empty(col):
        if col not in df.columns:
            return True
        s = df[col].fillna("").astype(str).str.strip()
        return (s == "") | (s.str.lower() == "nan")

    inst_empty = is_col_empty("Institution")
    office_empty = is_col_empty("Office")
    col_empty = is_col_empty("Column_num")
    ref_empty = is_col_empty("Reference")

    border_mask = is_letter_header & inst_empty & office_empty & col_empty & ref_empty
    num_dropped = border_mask.sum()
    if num_dropped > 0:
        dropped_places = df.loc[border_mask, "Place"].tolist()
        print(f"Removed {num_dropped} alphabet header row(s): {dropped_places}")
        df = df[~border_mask].reset_index(drop=True)

    return df


def apply_structured_place_fixes(df):
    """
    Corrects remaining absorption anomalies directly in structured DataFrames.
    """
    # 1. Pisa concilium ... doctor 62. civit. 141.
    pisa_mask = df["Place"].astype(str).str.contains(r"^Pisa\s+concilium", regex=True, na=False)
    if pisa_mask.any():
        print(f"Fixing {pisa_mask.sum()} structured Pisa row(s)...")
        pisa_rows = [
            {"Place": "Pisa", "Name Variant": "", "Diocese": "", "Institution": "", "Office": "concilium", "Column_num": format_column_numbers("8 16 29 39 105 171 191 239 308 336"), "Reference": ""},
            {"Place": "Pisa", "Name Variant": "", "Diocese": "", "Institution": "", "Office": "doctor", "Column_num": "62", "Reference": ""},
            {"Place": "Pisa", "Name Variant": "", "Diocese": "", "Institution": "", "Office": "civit.", "Column_num": "141", "Reference": ""},
        ]
        insert_idx = df[pisa_mask].index[0]
        df_cleaned = df.drop(index=df[pisa_mask].index)
        df = pd.concat([df_cleaned.iloc[:insert_idx], pd.DataFrame(pisa_rows), df_cleaned.iloc[insert_idx:]]).reset_index(drop=True)

    # 2. Conneux where body bled into Name Variant or was trapped in Place
    conneux_bleed = (df["Place"].astype(str).str.strip() == "Conneux") & (
        df["Name Variant"].astype(str).str.contains(r"par\.\s*eccl\.", na=False)
    )
    if conneux_bleed.any():
        df.loc[conneux_bleed, "Place"] = "Conneux"
        df.loc[conneux_bleed, "Name Variant"] = "? Concheyum"
        df.loc[conneux_bleed, "Diocese"] = "Leod. dioc."
        df.loc[conneux_bleed, "Institution"] = "par. eccl."
        df.loc[conneux_bleed, "Office"] = ""
        df.loc[conneux_bleed, "Column_num"] = "187"

    conneux_place = df["Place"].astype(str).str.contains(r"^Conneux\s*\(", regex=True, na=False)
    if conneux_place.any():
        df.loc[conneux_place, "Place"] = "Conneux"
        df.loc[conneux_place, "Name Variant"] = "? Concheyum"
        df.loc[conneux_place, "Diocese"] = "Leod. dioc."
        df.loc[conneux_place, "Institution"] = "par. eccl."
        df.loc[conneux_place, "Office"] = ""
        df.loc[conneux_place, "Column_num"] = "187"

    # 3. Balsamgau where body bled into Name Variant or was trapped in Place
    balsamgau_bleed = (df["Place"].astype(str).str.strip() == "Balsamgau") & (
        df["Name Variant"].astype(str).str.contains(r"archidiacon\.", na=False)
    )
    if balsamgau_bleed.any():
        df.loc[balsamgau_bleed, "Place"] = "Balsamgau"
        df.loc[balsamgau_bleed, "Name Variant"] = "Balsamia"
        df.loc[balsamgau_bleed, "Diocese"] = "Halberst. dioc."
        df.loc[balsamgau_bleed, "Institution"] = ""
        df.loc[balsamgau_bleed, "Office"] = "archidiacon."
        df.loc[balsamgau_bleed, "Column_num"] = "105"

    balsamgau_place = df["Place"].astype(str).str.contains(r"^Balsamgau\s*\(", regex=True, na=False)
    if balsamgau_place.any():
        df.loc[balsamgau_place, "Place"] = "Balsamgau"
        df.loc[balsamgau_place, "Name Variant"] = "Balsamia"
        df.loc[balsamgau_place, "Diocese"] = "Halberst. dioc."
        df.loc[balsamgau_place, "Institution"] = ""
        df.loc[balsamgau_place, "Office"] = "archidiacon."
        df.loc[balsamgau_place, "Column_num"] = "105"

    # 4. Kurzelow where body bled into Name Variant or Place
    kurzelow_bleed = (df["Place"].astype(str).str.strip() == "Kurzelow") & (
        df["Name Variant"].astype(str).str.contains(r"eccl\.:", na=False)
    )
    if kurzelow_bleed.any():
        df.loc[kurzelow_bleed, "Place"] = "Kurzelow"
        df.loc[kurzelow_bleed, "Name Variant"] = "Curzelouien."
        df.loc[kurzelow_bleed, "Diocese"] = "Gnezn. dioc."
        df.loc[kurzelow_bleed, "Institution"] = "eccl."
        df.loc[kurzelow_bleed, "Office"] = "decan."
        df.loc[kurzelow_bleed, "Column_num"] = "309"

    kurzelow_place = df["Place"].astype(str).str.contains(r"^Kurzelow\s*\(", regex=True, na=False)
    if kurzelow_place.any():
        df.loc[kurzelow_place, "Place"] = "Kurzelow"
        df.loc[kurzelow_place, "Name Variant"] = "Curzelouien."
        df.loc[kurzelow_place, "Diocese"] = "Gnezn. dioc."
        df.loc[kurzelow_place, "Institution"] = "eccl."
        df.loc[kurzelow_place, "Office"] = "decan."
        df.loc[kurzelow_place, "Column_num"] = "309"

    # 5. Toggenburg com. 122.
    toggen_mask = df["Place"].astype(str).str.contains(r"^Toggenburg\.?\s+(com\.|comes)", regex=True, na=False)
    if toggen_mask.any():
        for idx in df[toggen_mask].index:
            raw_p = df.loc[idx, "Place"]
            m = re.match(r"^(Toggenburg)\.?\s+(com\.|comes)\s+([\d\s]+)\.?$", raw_p)
            if m:
                df.loc[idx, "Place"] = m.group(1).strip()
                df.loc[idx, "Institution"] = ""
                df.loc[idx, "Office"] = m.group(2).strip()
                df.loc[idx, "Column_num"] = format_column_numbers(m.group(3).strip())

    # 6. Villafranca portus 334.
    villafranca_mask = df["Place"].astype(str).str.contains(r"^Villafranca\s+portus", regex=True, na=False)
    if villafranca_mask.any():
        df.loc[villafranca_mask, "Place"] = "Villafranca"
        df.loc[villafranca_mask, "Institution"] = ""
        df.loc[villafranca_mask, "Office"] = "portus"
        df.loc[villafranca_mask, "Column_num"] = "334"

    # 7. Werle dominus terre 60 192.
    werle_mask = df["Place"].astype(str).str.contains(r"^Werle\s+dominus\s+terre", regex=True, na=False)
    if werle_mask.any():
        df.loc[werle_mask, "Place"] = "Werle"
        df.loc[werle_mask, "Institution"] = "dominus terre"
        df.loc[werle_mask, "Office"] = ""
        df.loc[werle_mask, "Column_num"] = "60, 192"

    # 8. Amatia advocatus 61.
    amatia_mask = df["Place"].astype(str).str.contains(r"^Amatia\s+advocatus", regex=True, na=False)
    if amatia_mask.any():
        df.loc[amatia_mask, "Place"] = "Amatia"
        df.loc[amatia_mask, "Institution"] = ""
        df.loc[amatia_mask, "Office"] = "advocatus"
        df.loc[amatia_mask, "Column_num"] = "61"

    # 9. Generic trailing 'comes / com. / comites / comitissa <digits>'
    comes_mask = df["Place"].astype(str).str.contains(
        r"^(.+?)\.?\s+(comes|com\.|comites|comitissa)\s+([\d\s]+)\.?$", regex=True, na=False
    )
    if comes_mask.any():
        for idx in df[comes_mask].index:
            raw_place_str = df.loc[idx, "Place"]
            m = re.match(
                r"^(.+?)\.?\s+(comes|com\.|comites|comitissa)\s+([\d\s]+)\.?$", raw_place_str
            )
            if m:
                df.loc[idx, "Place"] = m.group(1).strip().rstrip(".")
                df.loc[idx, "Office"] = m.group(2).strip()
                df.loc[idx, "Column_num"] = format_column_numbers(m.group(3).strip())

    # 10. Greifswald structured fallback guarantee
    greifswald_mask = (df["Place"].astype(str).str.strip() == "Greifswald") & (
        df["Institution"].astype(str).str.contains(r"Nicolai", na=False)
    )
    if greifswald_mask.any():
        rows_data = []
        for _, r in df[df["Place"].astype(str).str.strip() == "Greifswald"].iterrows():
            rows_data.append(r)
        insts = [str(r.get("Institution", "")) for r in rows_data]
        if not any("Nicolai" in i and r.get("Office") == "prepos." for r, i in zip(rows_data, insts)):
            print("Applying structural guarantee for Greifswald...")
            g_idx = df[df["Place"].astype(str).str.strip() == "Greifswald"].index
            clean_g_rows = [
                {
                    "Place": "Greifswald",
                    "Name Variant": "Gripeswoldis",
                    "Diocese": "Camin. dioc.",
                    "Institution": "par. eccl. s. Marie",
                    "Office": "",
                    "Column_num": "85",
                    "Reference": "",
                },
                {
                    "Place": "Greifswald",
                    "Name Variant": "Gripeswoldis",
                    "Diocese": "Camin. dioc.",
                    "Institution": "(par.) eccl. s. Nicolai",
                    "Office": "",
                    "Column_num": "85",
                    "Reference": "",
                },
                {
                    "Place": "Greifswald",
                    "Name Variant": "Gripeswoldis",
                    "Diocese": "Camin. dioc.",
                    "Institution": "(par.) eccl. s. Nicolai",
                    "Office": "prepos.",
                    "Column_num": "137",
                    "Reference": "",
                },
            ]
            start_i = g_idx[0]
            df_dropped = df.drop(index=g_idx)
            df = pd.concat(
                [df_dropped.iloc[:start_i], pd.DataFrame(clean_g_rows), df_dropped.iloc[start_i:]]
            ).reset_index(drop=True)

    # 11. Amsterdam structured fallback guarantee
    amsterdam_mask = df["Place"].astype(str).str.strip() == "Amsterdam"
    if amsterdam_mask.any():
        a_rows = df[amsterdam_mask]
        inst_texts = a_rows["Institution"].fillna("").astype(str).tolist()
        # Verify if Nieuwe-Zijdskapel was properly split or absorbed
        if not any("Nieuwe-Zijdskapel" in it for it in inst_texts) or len(a_rows) < 2:
            print("Applying structural guarantee for Amsterdam...")
            a_idx = df[amsterdam_mask].index
            clean_a_rows = [
                {
                    "Place": "Amsterdam",
                    "Name Variant": "Aemsterdam",
                    "Diocese": "Traiect. dioc.",
                    "Institution": "par. eccl.",
                    "Office": "",
                    "Column_num": "62, 373",
                    "Reference": "",
                },
                {
                    "Place": "Amsterdam",
                    "Name Variant": "Aemsterdam",
                    "Diocese": "Traiect. dioc.",
                    "Institution": "Nieuwe-Zijdskapel (Heiligestede)",
                    "Office": "",
                    "Column_num": "373",
                    "Reference": "",
                },
            ]
            start_a = a_idx[0]
            df_dropped = df.drop(index=a_idx)
            df = pd.concat(
                [df_dropped.iloc[:start_a], pd.DataFrame(clean_a_rows), df_dropped.iloc[start_a:]]
            ).reset_index(drop=True)

    return df


# ==============================================================================
# 6. PIPELINE ORCHESTRATOR
# ==============================================================================

def run_full_extraction_pipeline(
    input_csv="ortsverzeichnis_vol3_raw_final_fixed.csv",
    output_structured_csv="ortsverzeichnis_vol3_structured_par_fixed.csv",
    output_no_ref_csv="ortsverzeichnis_vol3_no_references.csv",
    output_ref_only_csv="ortsverzeichnis_vol3_references_only.csv",
    output_missing_cols_csv="flagged_missing_column_num_1.csv",
):
    if not os.path.exists(input_csv):
        print(f"Error: Input file '{input_csv}' not found.")
        return

    print(f"Loading raw source from: '{input_csv}'...")
    df_raw = pd.read_csv(input_csv, encoding="utf-8-sig")
    raw_col = "raw_entry" if "raw_entry" in df_raw.columns else df_raw.columns[0]
    print(f"Input records to extract: {len(df_raw)}")

    # --------------------------------------------------------------------------
    # STEP 1: Parse and structure raw records
    # --------------------------------------------------------------------------
    print("\n[Step 1/4] Parsing raw index entries...")
    structured_rows = []

    for _, row in df_raw.iterrows():
        raw_text = str(row[raw_col]).strip()
        if not raw_text or raw_text == "nan":
            continue

        raw_text = patch_special_raw_entries(raw_text)
        place, variants, diocese, body, cross_ref = parse_place_header(raw_text)

        if cross_ref:
            structured_rows.append({
                "Place": place,
                "Name Variant": variants,
                "Diocese": diocese,
                "Institution": "",
                "Office": "",
                "Column_num": "",
                "Reference": cross_ref,
            })
            continue

        records = parse_body_institutions_and_offices(body)

        if records:
            for rec in records:
                # Strip helper prefix from Amsterdam if processed via raw patch
                inst_cleaned = rec["institution"]
                if inst_cleaned.startswith("capel. Nieuwe-Zijdskapel"):
                    inst_cleaned = inst_cleaned.replace("capel. ", "", 1)

                structured_rows.append({
                    "Place": place,
                    "Name Variant": variants,
                    "Diocese": diocese,
                    "Institution": inst_cleaned,
                    "Office": rec["office"],
                    "Column_num": rec["column_num"],
                    "Reference": "",
                })
        else:
            structured_rows.append({
                "Place": place,
                "Name Variant": variants,
                "Diocese": diocese,
                "Institution": "",
                "Office": "",
                "Column_num": "",
                "Reference": "",
            })

    df_structured = pd.DataFrame(
        structured_rows,
        columns=[
            "Place",
            "Name Variant",
            "Diocese",
            "Institution",
            "Office",
            "Column_num",
            "Reference",
        ],
    )

    # --------------------------------------------------------------------------
    # STEP 2: Merge parish rows & apply structured overrides
    # --------------------------------------------------------------------------
    print("[Step 2/4] Consolidating parish rows and applying structural fixes...")
    cleaned_rows = merge_par_records(df_structured.to_dict("records"))
    df_structured = pd.DataFrame(cleaned_rows)
    df_structured = apply_structured_place_fixes(df_structured)
    df_structured = remove_alphabet_border_rows(df_structured)
    df_structured = df_structured.map(fix_mojibake_str)

    # Save full structured dataset
    df_structured.to_csv(output_structured_csv, index=False, encoding="utf-8-sig")
    print(f"  -> Saved full structured file: '{output_structured_csv}' ({len(df_structured)} rows)")

    # --------------------------------------------------------------------------
    # STEP 3: Separate cross-references vs. substantive data
    # --------------------------------------------------------------------------
    print("\n[Step 3/4] Separating cross-references from substantive records...")
    has_ref_mask = (
        df_structured["Reference"].fillna("").astype(str).str.strip().ne("")
        & df_structured["Reference"].fillna("").astype(str).str.lower().ne("nan")
    )
    ref_count = has_ref_mask.sum()

    # Save references-only (Place + Reference only)
    df_ref_only = df_structured[has_ref_mask].copy().reset_index(drop=True)
    other_cols = [c for c in df_ref_only.columns if c not in ["Place", "Reference"]]
    for c in other_cols:
        df_ref_only[c] = ""
    df_ref_only.to_csv(output_ref_only_csv, index=False, encoding="utf-8-sig")
    print(f"  -> Saved references-only file: '{output_ref_only_csv}' ({ref_count} rows)")

    # Save non-reference records
    df_no_ref = df_structured[~has_ref_mask].copy().reset_index(drop=True)
    df_no_ref.to_csv(output_no_ref_csv, index=False, encoding="utf-8-sig")
    print(f"  -> Saved substantive file:     '{output_no_ref_csv}' ({len(df_no_ref)} rows)")

    # --------------------------------------------------------------------------
    # STEP 4: Audit rows missing column citations
    # --------------------------------------------------------------------------
    print("\n[Step 4/4] Auditing missing column numbers in substantive records...")
    missing_col_mask = (
        df_no_ref["Column_num"].fillna("").astype(str).str.strip().eq("")
        | df_no_ref["Column_num"].fillna("").astype(str).str.lower().eq("nan")
    )
    df_missing_cols = df_no_ref[missing_col_mask].copy()
    missing_count = len(df_missing_cols)

    print(f"Rows with NO value in 'Column_num': {missing_count}")
    print(f"Unique places affected:            {df_missing_cols['Place'].nunique()}")

    if missing_count > 0:
        df_missing_cols.to_csv(output_missing_cols_csv, index=True, encoding="utf-8-sig")
        print(f"  -> Exported audit flags to:    '{output_missing_cols_csv}'")
    else:
        print("  -> All substantive records contain a valid 'Column_num'.")

    print("\n" + "=" * 65)
    print("EXTRACTION AND STRUCTURING PIPELINE COMPLETE")
    print("=" * 65)


if __name__ == "__main__":
    run_full_extraction_pipeline()