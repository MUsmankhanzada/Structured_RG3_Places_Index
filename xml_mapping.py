import os
import re
import string
import pandas as pd


def normalize_headword(text):
    """Normalizes headwords for consistent matching across XML and CSV."""
    if not isinstance(text, str):
        return ""
    # Strip bracketed qualifiers, parentheses, and punctuation
    cleaned = re.sub(r"\(.*?\)|\[.*?\]", "", text)
    cleaned = re.sub(r"[\.,;:\"'!?]", "", cleaned)
    # Strip common Romance diacritics causing OCR/LLM spelling discrepancies
    cleaned = re.sub(r"[éè]", "e", cleaned)
    cleaned = re.sub(r"[áà]", "a", cleaned)
    cleaned = re.sub(r"[íì]", "i", cleaned)
    cleaned = re.sub(r"[óò]", "o", cleaned)
    cleaned = re.sub(r"[úù]", "u", cleaned)
    # Standardize German umlauts
    cleaned = cleaned.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    cleaned = cleaned.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def is_target_section_headword(text, char_prefix):
    """Checks if a headword belongs to a given letter section (A-Z, skipping J).

    Correctly routes German umlauts and Saint entries (e.g., 'St. Florian' -> F).
    """
    if not isinstance(text, str):
        return False
    s = text.strip()
    char = char_prefix.lower()

    umlaut = ""
    if char == "a":
        umlaut = "ä"
    elif char == "o":
        umlaut = "ö"
    elif char == "u":
        umlaut = "ü"

    char_class = f"{char}{char.upper()}{umlaut}{umlaut.upper()}"

    # 1. Direct initial character match
    if re.match(rf"^[{char_class}]", s):
        return True

    # 2. 'St.' or 'S.' followed by the target saint headword letter
    if re.match(rf"^(?:St\.|S\.)\s+[{char_class}]", s, re.IGNORECASE):
        return True

    return False


def locate_xml_path(section_char, xml_dir="xml_files"):
    """Searches for XML files matching section letter inside xml_dir."""
    char_lower = section_char.lower()
    candidates = [
        os.path.join(xml_dir, f"orte_rg3_{char_lower}.xml"),
        os.path.join(xml_dir, f"orte_rg3_{char_lower}(1).xml"),
        os.path.join(xml_dir, f"orte_rg3_{char_lower}"),
        os.path.join(xml_dir, f"orte_rg3_{char_lower}(1)"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def parse_custom_xml_file(xml_path):
    """Extracts <ort id="..."> and <name> contents, excluding all cross-references (' v.

    ').
    """
    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"Could not find XML file: '{xml_path}'")

    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()

    ort_pattern = re.compile(
        r'<ort\s+id=["\'](\d+)["\']>(.*?)</ort>', re.DOTALL | re.IGNORECASE
    )
    name_pattern = re.compile(r"<name>(.*?)</name>", re.DOTALL | re.IGNORECASE)

    substantive_entries = []
    cross_references = []

    for match in ort_pattern.finditer(content):
        ort_id = match.group(1).strip()
        body = match.group(2).strip()

        name_match = name_pattern.search(body)
        if not name_match:
            continue

        raw_name = name_match.group(1).strip()

        # Filter out cross-references
        if re.search(r"\bv\.\s+", raw_name, re.IGNORECASE) or raw_name.endswith(" v."):
            cross_references.append({
                "ort_id": ort_id,
                "raw_text": raw_name,
            })
            continue

        # Extract headword before inline milestone markers <ka/> or <ka>
        if "<ka/>" in raw_name:
            headword = raw_name.split("<ka/>")[0].strip().rstrip(".")
        elif "<ka>" in raw_name:
            headword = raw_name.split("<ka>")[0].strip().rstrip(".")
        else:
            headword = re.sub(r"<[^>]+>", "", raw_name).strip().rstrip(".")

        substantive_entries.append({
            "ort_id": ort_id,
            "place_headword": headword,
            "norm_key": normalize_headword(headword),
            "raw_name": raw_name,
        })

    return substantive_entries, cross_references


def extract_cross_reference_aliases(raw_name):
    """Returns a cross-reference's primary alias and rendered milestone variants."""
    raw_alias = re.split(
        r"\bv\.(?:\s+|$)", raw_name, maxsplit=1, flags=re.IGNORECASE
    )[0].strip()
    primary_alias = re.split(
        r"<ka\s*/?>", raw_alias, maxsplit=1, flags=re.IGNORECASE
    )[0]
    primary_alias = re.sub(r"<[^>]+>", "", primary_alias).strip().rstrip(".")

    rendered_alias = re.sub(r"<ka\s*/?>", "(", raw_alias, flags=re.IGNORECASE)
    rendered_alias = re.sub(r"<kz\s*/?>", ")", rendered_alias, flags=re.IGNORECASE)
    rendered_alias = re.sub(r"<[^>]+>", "", rendered_alias).strip().rstrip(".")
    return primary_alias, rendered_alias


def map_and_audit_all_letters(
    csv_path="ortsverzeichnis_vol3_no_references.csv",
    xml_dir="xml_files",
    output_mapped_csv="ortsverzeichnis_vol3_no_references_mapped.csv",
    output_audit_csv="audit_extra_in_xml.csv",
    references_csv_path="ortsverzeichnis_vol3_references_only.csv",
    references_output_mapped_csv="ortsverzeichnis_vol3_references_only_mapped.csv",
    references_audit_csv="audit_references_discrepancies_remaining.csv",
    reviewed_references_csv_path="ortsverzeichnis_vol3_references_only_mapped_fixed.csv",
    xml_corrections_csv="xml_spelling_corrections.csv",
):
    target_letters = [ch for ch in string.ascii_uppercase if ch != "J"]

    # --------------------------------------------------------------------------
    # 1. PARSE ALL DISCOVERED XML FILES
    # --------------------------------------------------------------------------
    all_substantive_xml = []
    all_cross_references = []
    total_refs_dropped = 0
    available_sections = []

    print("=" * 80)
    print(f"1. SCANNING AND PARSING ALL XML SOURCES IN '{xml_dir}/' (A-Z EXCLUDING J)")
    print("=" * 80)

    for section in target_letters:
        target_path = locate_xml_path(section, xml_dir=xml_dir)

        if not target_path:
            print(f"[Notice] Section [{section}]: File not found in '{xml_dir}/'. Skipping.")
            continue

        available_sections.append(section)
        sub_list, ref_list = parse_custom_xml_file(target_path)
        for entry in sub_list:
            entry["section"] = section
        all_substantive_xml.extend(sub_list)
        all_cross_references.extend(ref_list)
        total_refs_dropped += len(ref_list)

        print(
            f"Section [{section}] -> File: '{target_path:<30}' | "
            f"Substantive: {len(sub_list):4d} | Refs Dropped: {len(ref_list):4d}"
        )

    print("\n" + "-" * 80)
    print(f"Total XML Sections Loaded:                {len(available_sections)}")
    print(f"Total Master Substantive XML Headwords:   {len(all_substantive_xml)}")
    print(f"Total Cross-References Excluded:          {total_refs_dropped}")

    df_xml_all = pd.DataFrame(all_substantive_xml)
    if df_xml_all.empty:
        print(f"No XML files found in folder '{xml_dir}'. Please verify the directory path.")
        return

    # --------------------------------------------------------------------------
    # 2. PARSE SUBSTANTIVE CSV
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("2. PARSING CSV DATASET")
    print("=" * 80)

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Could not find CSV file: '{csv_path}'")

    df_csv = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"Loaded '{csv_path}' with {len(df_csv)} total rows.")
    df_csv["Place_Clean"] = df_csv["Place"].fillna("").astype(str).str.strip()

    # --------------------------------------------------------------------------
    # 3. AUDIT PER SECTION & COLLECT ONLY XML-EXTRA (NOT IN CSV)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("3. SECTION-BY-SECTION AUDIT")
    print("=" * 80)

    discrepancy_report = []
    extra_in_xml_records = []

    for section in available_sections:
        df_xml_sec = df_xml_all[df_xml_all["section"] == section]
        if df_xml_sec.empty:
            continue

        sec_mask = df_csv["Place_Clean"].apply(lambda p: is_target_section_headword(p, section))
        df_csv_sec = df_csv[sec_mask]
        unique_csv_places = df_csv_sec["Place_Clean"].unique().tolist()

        df_csv_unique = pd.DataFrame({
            "Place": unique_csv_places,
            "norm_key": [normalize_headword(p) for p in unique_csv_places],
        })

        comparison = pd.merge(
            df_csv_unique,
            df_xml_sec[["norm_key", "ort_id", "place_headword", "raw_name"]].drop_duplicates(subset=["norm_key"]),
            on="norm_key",
            how="outer",
            indicator=True,
        )

        matched = comparison[comparison["_merge"] == "both"]
        xml_missing_in_csv = comparison[comparison["_merge"] == "right_only"]

        discrepancy_report.append({
            "Section": section,
            "CSV_Unique": len(unique_csv_places),
            "XML_Substantive": len(df_xml_sec),
            "Matched": len(matched),
            "Extra_in_XML": len(xml_missing_in_csv),
        })

        # Append ONLY entries that are in XML and NOT in CSV
        for _, r in xml_missing_in_csv.iterrows():
            extra_in_xml_records.append({
                "Section": section,
                "ort_id": r["ort_id"],
                "place_headword": r["place_headword"],
                "xml_full_name": r.get("raw_name", ""),
                "norm_key": r["norm_key"],
            })

        if not xml_missing_in_csv.empty:
            print(f"\n[!] Extra in XML (Not in CSV) for Section [{section}]: {len(xml_missing_in_csv)}")
            for _, r in xml_missing_in_csv.iterrows():
                print(f"    * ID: {r['ort_id']} | '{r['place_headword']}'")

    # High-level summary table
    print("\n" + "=" * 80)
    print(f"{'Section':<8} | {'CSV Unique':<12} | {'XML Subs':<10} | {'Matched':<9} | {'Extra in XML (Missing in CSV)':<30}")
    print("-" * 80)
    for r in discrepancy_report:
        print(
            f"{r['Section']:<8} | {r['CSV_Unique']:<12} | {r['XML_Substantive']:<10} | "
            f"{r['Matched']:<9} | {r['Extra_in_XML']:<30}"
        )

    # --------------------------------------------------------------------------
    # 4. EXPORT ONLY ENTRIES EXTRA IN XML TO AUDIT CSV
    # --------------------------------------------------------------------------
    df_audit_export = pd.DataFrame(extra_in_xml_records)
    df_audit_export.to_csv(output_audit_csv, index=False, encoding="utf-8-sig")
    print("\n" + "-" * 80)
    print(f"Audit CSV exported: {len(df_audit_export)} record(s) extra in XML -> '{output_audit_csv}'")

    # --------------------------------------------------------------------------
    # 5. MAP ORT_ID AND EXPORT
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("5. MAPPING ORT_ID AND WRITING CSV")
    print("=" * 80)

    key_to_id = dict(zip(df_xml_all["norm_key"], df_xml_all["ort_id"]))

    if "ort_id" in df_csv.columns:
        df_csv["ort_id"] = df_csv.apply(
            lambda row: row["ort_id"]
            if pd.notna(row["ort_id"]) and str(row["ort_id"]).strip() != ""
            else key_to_id.get(normalize_headword(row["Place_Clean"]), ""),
            axis=1,
        )
    else:
        df_csv["ort_id"] = df_csv["Place_Clean"].apply(
            lambda p: key_to_id.get(normalize_headword(p), "")
        )

    cols = ["ort_id"] + [c for c in df_csv.columns if c not in ("ort_id", "Place_Clean")]
    df_mapped = df_csv[cols]

    df_mapped.to_csv(output_mapped_csv, index=False, encoding="utf-8-sig")

    mapped_count = (df_mapped["ort_id"].fillna("").astype(str).str.strip() != "").sum()
    print(f"Total Rows with Matched 'ort_id' : {mapped_count} / {len(df_mapped)}")
    print(f"Saved complete mapped dataset to : '{output_mapped_csv}'")

    # Map reference aliases to the IDs of their XML cross-reference entries.
    reference_xml_records = []
    reference_key_to_id = {}
    for entry in all_cross_references:
        primary_alias, alias = extract_cross_reference_aliases(entry["raw_text"])
        norm_key = normalize_headword(alias)
        for alias_key in {norm_key, normalize_headword(primary_alias)}:
            if alias_key:
                reference_key_to_id[alias_key] = entry["ort_id"]
        reference_xml_records.append({
            "xml_alias": alias,
            "xml_raw_name": entry["raw_text"],
            "xml_ort_id": entry["ort_id"],
            "norm_key": norm_key,
        })

    reference_input_path = (
        reviewed_references_csv_path
        if os.path.exists(reviewed_references_csv_path)
        else references_csv_path
    )
    if not os.path.exists(reference_input_path):
        raise FileNotFoundError(f"Could not find CSV file: '{reference_input_path}'")

    df_references = pd.read_csv(
        reference_input_path,
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
    )
    print(f"Loaded references-only CSV '{reference_input_path}' with {len(df_references)} rows.")
    df_references["Place_Clean"] = (
        df_references["Place"].fillna("").astype(str).str.strip()
    )

    # Compare unique normalized aliases while retaining their original spellings.
    df_reference_csv_keys = pd.DataFrame({
        "csv_place": df_references["Place_Clean"],
        "norm_key": df_references["Place_Clean"].apply(normalize_headword),
        "csv_ort_id": df_references.get(
            "ort_id", pd.Series("", index=df_references.index)
        ).fillna("").astype(str),
    })
    df_reference_csv_keys = df_reference_csv_keys[
        df_reference_csv_keys["norm_key"] != ""
    ].drop_duplicates(subset=["norm_key"])
    df_reference_xml_keys = pd.DataFrame(
        reference_xml_records,
        columns=["xml_alias", "xml_raw_name", "xml_ort_id", "norm_key"],
    )
    df_reference_xml_keys = df_reference_xml_keys[
        df_reference_xml_keys["norm_key"] != ""
    ].drop_duplicates(subset=["norm_key"])
    reference_comparison = pd.merge(
        df_reference_csv_keys,
        df_reference_xml_keys,
        on="norm_key",
        how="outer",
        indicator=True,
    )
    discrepancy_rows = reference_comparison[reference_comparison["_merge"] != "both"].copy()
    if os.path.exists(xml_corrections_csv):
        df_xml_corrections = pd.read_csv(
            xml_corrections_csv, encoding="utf-8-sig", dtype=str
        ).fillna("")
        if {"ort_id", "XML spelling", "Correct spelling"}.issubset(df_xml_corrections.columns):
            corrected_ids = set(df_xml_corrections["ort_id"].str.strip())
            corrected_keys = set(
                df_xml_corrections["XML spelling"].apply(normalize_headword)
            ) | set(df_xml_corrections["Correct spelling"].apply(normalize_headword))
            csv_ids = discrepancy_rows.get(
                "csv_ort_id", pd.Series("", index=discrepancy_rows.index)
            ).fillna("").astype(str).str.strip()
            xml_ids = discrepancy_rows.get(
                "xml_ort_id", pd.Series("", index=discrepancy_rows.index)
            ).fillna("").astype(str).str.strip()
            known_csv_corrections = (
                (discrepancy_rows["_merge"] == "left_only")
                & (
                    discrepancy_rows["norm_key"].isin(corrected_keys)
                    | csv_ids.isin(corrected_ids)
                )
            )
            known_xml_corrections = (
                (discrepancy_rows["_merge"] == "right_only")
                & (
                    discrepancy_rows["norm_key"].isin(corrected_keys)
                    | xml_ids.isin(corrected_ids)
                )
            )
            discrepancy_rows = discrepancy_rows[
                ~(known_csv_corrections | known_xml_corrections)
            ]

    reference_discrepancies = []
    for _, row in discrepancy_rows.iterrows():
        reference_discrepancies.append({
            "Discrepancy": "Missing in XML" if row["_merge"] == "left_only" else "Missing in CSV",
            "CSV Place": row.get("csv_place", ""),
            "XML Alias": row.get("xml_alias", ""),
            "XML Raw Name": row.get("xml_raw_name", ""),
            "XML ort_id": row.get("xml_ort_id", ""),
            "Normalized Key": row["norm_key"],
        })
    df_reference_discrepancies = pd.DataFrame(
        reference_discrepancies,
        columns=[
            "Discrepancy",
            "CSV Place",
            "XML Alias",
            "XML Raw Name",
            "XML ort_id",
            "Normalized Key",
        ],
    )
    df_reference_discrepancies.to_csv(
        references_audit_csv, index=False, encoding="utf-8-sig"
    )
    missing_in_xml_count = (df_reference_discrepancies["Discrepancy"] == "Missing in XML").sum()
    missing_in_csv_count = (df_reference_discrepancies["Discrepancy"] == "Missing in CSV").sum()
    print(
        f"References-only discrepancies: {missing_in_xml_count} missing in XML, "
        f"{missing_in_csv_count} missing in CSV -> '{references_audit_csv}'"
    )

    if "ort_id" in df_references.columns:
        df_references["ort_id"] = df_references.apply(
            lambda row: row["ort_id"]
            if pd.notna(row["ort_id"]) and str(row["ort_id"]).strip() != ""
            else reference_key_to_id.get(normalize_headword(row["Place_Clean"]), ""),
            axis=1,
        )
    else:
        df_references["ort_id"] = df_references["Place_Clean"].apply(
            lambda place: reference_key_to_id.get(normalize_headword(place), "")
        )

    reference_cols = [
        "ort_id"
    ] + [
        column
        for column in df_references.columns
        if column not in ("ort_id", "Place_Clean")
    ]
    df_references_mapped = df_references[reference_cols]
    df_references_mapped.to_csv(
        references_output_mapped_csv, index=False, encoding="utf-8-sig"
    )

    references_mapped_count = (
        df_references_mapped["ort_id"].fillna("").astype(str).str.strip() != ""
    ).sum()
    print(
        f"References-only rows with matched 'ort_id': "
        f"{references_mapped_count} / {len(df_references_mapped)}"
    )
    print(f"Saved mapped references-only dataset to : '{references_output_mapped_csv}'")
    print("=" * 80)


if __name__ == "__main__":
    map_and_audit_all_letters(xml_dir="xml_files")