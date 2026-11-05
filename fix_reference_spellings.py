import os
import re
import string
from difflib import SequenceMatcher

import pandas as pd

from xml_mapping import locate_xml_path, normalize_headword, parse_custom_xml_file


INPUT_CSV = "ortsverzeichnis_vol3_references_only_mapped.csv"
OUTPUT_CSV = "ortsverzeichnis_vol3_references_only_mapped_fixed.csv"
XML_CORRECTIONS_CSV = "xml_spelling_corrections.csv"
AUDIT_CSV = "audit_references_discrepancies_remaining.csv"
AUDIT_START_ROW = 2

PLACE_CORRECTIONS = {
    "Almaria": "Alcmaria",
    "Bergungin": "Bercgungin",
    "Boydnghen": "Boydinghen",
    "Dankirchen": "Dankirichen",
    "Drybilshem": "Drybilsheim",
    "Dypburg": "Dyppurg",
    "Eckirchen": "Eckchirchen",
    "Empre": "Emptre",
    "Frescha": "Fresha",
    "Freynstät": "Freynstat",
    "Frisenhoven": "Frisenhouen",
    "Gheyspolshem": "Gheyspolsheim",
}

REFERENCE_CORRECTIONS = {
    "Gheyspolshem": "Geispolsheim",
}

MANUAL_ORT_IDS = {
    "Blittersdorf": "10300242",
    "Culm(u)ach": "10300454",
}

PLACES_TO_DELETE = {"Duurstede"}

XML_SPELLING_CORRECTIONS = [
    {
        "ort_id": "10300242",
        "XML spelling": "Bhttersdorf",
        "Correct spelling": "Blittersdorf",
    },
]


def build_reference_id_map(xml_dir="xml_files"):
    """Builds a normalized alias-to-ID map from XML cross-reference entries."""
    reference_ids = {}
    for section in [letter for letter in string.ascii_uppercase if letter != "J"]:
        xml_path = locate_xml_path(section, xml_dir=xml_dir)
        if not xml_path:
            continue

        _, cross_references = parse_custom_xml_file(xml_path)
        for entry in cross_references:
            raw_alias = re.split(
                r"\bv\.(?:\s+|$)",
                entry["raw_text"],
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            alias = re.split(
                r"<ka\s*/?>", raw_alias, maxsplit=1, flags=re.IGNORECASE
            )[0]
            alias = re.sub(r"<[^>]+>", "", alias).strip().rstrip(".")
            norm_key = normalize_headword(alias)
            if norm_key:
                reference_ids[norm_key] = entry["ort_id"]

    return reference_ids


def parse_xml_reference(raw_name):
    """Returns a cross-reference alias and its target, preserving XML variants."""
    parts = re.split(
        r"\bv\.(?:\s+|$)", raw_name, maxsplit=1, flags=re.IGNORECASE
    )
    if len(parts) != 2:
        return "", ""

    alias = re.sub(r"<ka\s*/?>", "(", parts[0], flags=re.IGNORECASE)
    alias = re.sub(r"<kz\s*/?>", ")", alias, flags=re.IGNORECASE)
    alias = re.sub(r"<[^>]+>", "", alias).strip().rstrip(".")
    target = re.sub(r"<[^>]+>", "", parts[1]).strip().rstrip(".")
    return alias, target


def alias_place_and_variant(alias):
    """Splits a trailing parenthesized alias variant into its own CSV field."""
    match = re.match(r"^(.*?)\s*\(([^()]*)\)$", alias)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return alias, ""


def apply_xml_audit_corrections(df, audit_csv=AUDIT_CSV, start_row=AUDIT_START_ROW):
    if not os.path.exists(audit_csv):
        raise FileNotFoundError(f"Could not find reference discrepancy audit: '{audit_csv}'")

    audit = pd.read_csv(audit_csv, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    required_columns = {"Discrepancy", "CSV Place", "XML Raw Name", "XML ort_id"}
    missing_columns = required_columns.difference(audit.columns)
    if missing_columns:
        raise ValueError(f"Audit CSV is missing required columns: {sorted(missing_columns)}")

    # CSV row numbers include the header, so physical row 33 is DataFrame index 31.
    audit_slice = audit.iloc[max(start_row - 2, 0):]
    missing_xml = audit[audit["Discrepancy"] == "Missing in XML"]
    missing_xml_keys = {
        normalize_headword(place)
        for place in missing_xml["CSV Place"]
        if normalize_headword(place)
    }
    source_indexes_by_key = {}
    for index, place in df["Place"].items():
        key = normalize_headword(place)
        if key in missing_xml_keys:
            source_indexes_by_key.setdefault(key, []).append(index)

    used_indexes = set()
    corrected_count = 0
    skipped_count = 0

    xml_rows = audit_slice[audit_slice["Discrepancy"] == "Missing in CSV"]
    for _, mismatch in xml_rows.iterrows():
        alias, target = parse_xml_reference(mismatch["XML Raw Name"])
        alias_key = normalize_headword(alias)
        if not alias_key or not target or not mismatch["XML ort_id"]:
            skipped_count += 1
            continue

        candidates = []
        for key, indexes in source_indexes_by_key.items():
            for index in indexes:
                if index in used_indexes:
                    continue
                place_key = normalize_headword(df.at[index, "Place"])
                score = SequenceMatcher(None, alias_key, place_key).ratio()
                if alias_key in place_key or place_key in alias_key:
                    score = max(score, min(len(alias_key), len(place_key)) / max(len(alias_key), len(place_key)))
                reference_matches = (
                    normalize_headword(df.at[index, "Reference"])
                    == normalize_headword(target)
                )
                candidates.append((reference_matches, score, index))

        candidates.sort(reverse=True)
        if not candidates or candidates[0][1] < 0.70:
            skipped_count += 1
            continue

        best_reference_match, best_score, best_index = candidates[0]
        competing_scores = [
            score
            for reference_match, score, _ in candidates[1:]
            if reference_match == best_reference_match
        ]
        if competing_scores and best_score - max(competing_scores) < 0.08:
            skipped_count += 1
            continue

        corrected_place, variant = alias_place_and_variant(alias)
        df.at[best_index, "Place"] = corrected_place
        df.at[best_index, "Reference"] = target
        df.at[best_index, "ort_id"] = mismatch["XML ort_id"]
        if variant and "Name Variant" in df.columns:
            current_variant = df.at[best_index, "Name Variant"].strip()
            if not current_variant or normalize_headword(current_variant) == normalize_headword(variant):
                df.at[best_index, "Name Variant"] = variant

        used_indexes.add(best_index)
        corrected_count += 1

    return corrected_count, skipped_count


def fix_reference_spellings(
    input_csv=INPUT_CSV,
    output_csv=OUTPUT_CSV,
    xml_corrections_csv=XML_CORRECTIONS_CSV,
    xml_dir="xml_files",
):
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Could not find mapped references CSV: '{input_csv}'")

    df = pd.read_csv(input_csv, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    required_columns = {"ort_id", "Place", "Reference"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Input CSV is missing required columns: {sorted(missing_columns)}")

    place_keys = df["Place"].str.strip().str.casefold()
    delete_mask = place_keys.isin({place.casefold() for place in PLACES_TO_DELETE})
    deleted_count = int(delete_mask.sum())
    df = df.loc[~delete_mask].copy()

    for source, corrected in PLACE_CORRECTIONS.items():
        source_key = source.casefold()
        corrected_key = corrected.casefold()
        matching_rows = df["Place"].str.strip().str.casefold().isin(
            {source_key, corrected_key}
        )
        if not matching_rows.any():
            raise ValueError(f"Could not find expected place spelling '{source}' in '{input_csv}'")
        df.loc[matching_rows, "Place"] = corrected

    for place, reference in REFERENCE_CORRECTIONS.items():
        corrected_place = PLACE_CORRECTIONS.get(place, place)
        matching_rows = df["Place"].str.strip().str.casefold() == corrected_place.casefold()
        if not matching_rows.any():
            raise ValueError(f"Could not find place '{corrected_place}' for reference correction")
        df.loc[matching_rows, "Reference"] = reference

    reference_ids = build_reference_id_map(xml_dir=xml_dir)
    for place in list(PLACE_CORRECTIONS.values()) + list(MANUAL_ORT_IDS):
        matching_rows = df["Place"].str.strip().str.casefold() == place.casefold()
        if not matching_rows.any():
            raise ValueError(f"Could not find expected corrected place '{place}'")

        ort_id = MANUAL_ORT_IDS.get(place)
        if ort_id is None:
            ort_id = reference_ids.get(normalize_headword(place))
        if not ort_id:
            raise ValueError(f"Could not resolve an XML ort_id for corrected place '{place}'")
        df.loc[matching_rows, "ort_id"] = ort_id

    audit_corrections, audit_skipped = apply_xml_audit_corrections(df)

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        XML_SPELLING_CORRECTIONS,
        columns=["ort_id", "XML spelling", "Correct spelling"],
    ).to_csv(xml_corrections_csv, index=False, encoding="utf-8-sig")

    print(f"Corrected references CSV saved: {output_csv}")
    print(f"XML spelling corrections saved: {xml_corrections_csv}")
    print(f"Duurstede entries removed: {deleted_count}")
    print(f"Additional XML-audit CSV corrections applied: {audit_corrections}")
    print(f"XML-audit rows skipped (no clear CSV match): {audit_skipped}")
    print(f"Rows in corrected references CSV: {len(df)}")


if __name__ == "__main__":
    fix_reference_spellings()