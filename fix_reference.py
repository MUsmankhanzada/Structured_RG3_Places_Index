import os
import re
import pandas as pd


def clean_place_casing(text):
    """Normalizes errant OCR / LLM capitalization (e.g.

    'YsonTIUS' -> 'Ysontius', 'ISONZO' -> 'Isonzo') while preserving intended
    multi-word capitalization.
    """
    if not isinstance(text, str) or not text.strip():
        return text

    def fix_token(token):
        letters = re.findall(r"[a-zA-ZäöüÄÖÜß]", token)
        if len(letters) >= 2:
            has_internal_upper = any(c.isupper() for c in token[1:])
            if token.isupper() or has_internal_upper:
                prefix = re.match(r"^[^a-zA-ZäöüÄÖÜß]*", token).group(0)
                suffix = re.search(r"[^a-zA-ZäöüÄÖÜß]*$", token).group(0)
                core = token[len(prefix) : len(token) - len(suffix)]
                if core:
                    return prefix + core.capitalize() + suffix
        return token

    tokens = text.split()
    cleaned_tokens = [fix_token(t) for t in tokens]
    return " ".join(cleaned_tokens)


def split_bracket_variants_and_fix_casing(
    input_csv="ortsverzeichnis_vol3_references_only.csv",
    output_csv="ortsverzeichnis_vol3_references_only_cleaned.csv",
):
    if not os.path.exists(input_csv):
        print(f"Error: Could not find '{input_csv}'.")
        return

    df = pd.read_csv(input_csv, encoding="utf-8-sig")
    print(f"Loaded '{input_csv}' with {len(df)} rows.")

    split_count = 0
    casing_count = 0

    for idx, row in df.iterrows():
        raw_place = str(row["Place"]).strip() if pd.notna(row["Place"]) else ""
        raw_ref = (
            str(row["Reference"]).strip() if pd.notna(row["Reference"]) else ""
        )

        # 1. Split bracketed variants in Place (e.g., 'Aldensalen. (Aldenzalen)')
        bracket_match = re.match(r"^(.+?)\s*\(([^)]+)\)\.?$", raw_place)
        if bracket_match:
            main_place = bracket_match.group(1).strip().rstrip(".")
            variant_val = bracket_match.group(2).strip().rstrip(".")

            df.at[idx, "Place"] = main_place
            df.at[idx, "Name Variant"] = variant_val
            split_count += 1
            raw_place = main_place

        # 2. Fix capitalization anomalies (e.g., 'YsonTIUS' -> 'Ysontius', 'ISONZO' -> 'Isonzo')
        cleaned_place = clean_place_casing(raw_place)
        cleaned_ref = clean_place_casing(raw_ref)

        if cleaned_place != raw_place:
            df.at[idx, "Place"] = cleaned_place
            casing_count += 1

        if cleaned_ref != raw_ref:
            df.at[idx, "Reference"] = cleaned_ref
            casing_count += 1

        # Normalize casing on Name Variant if present
        curr_variant = (
            str(df.at[idx, "Name Variant"]).strip()
            if pd.notna(df.at[idx, "Name Variant"])
            else ""
        )
        if curr_variant and curr_variant != "nan":
            cleaned_variant = clean_place_casing(curr_variant)
            if cleaned_variant != curr_variant:
                df.at[idx, "Name Variant"] = cleaned_variant
                casing_count += 1

    # Keep only Place, Name Variant, and Reference populated
    blank_cols = [
        c
        for c in df.columns
        if c not in ["Place", "Name Variant", "Reference"]
    ]
    for col in blank_cols:
        df[col] = ""

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("\n--- Processing Summary ---")
    print(
        f"Bracketed Place entries split into Name Variant: {split_count}"
    )
    print(f"Capitalization errors corrected:                 {casing_count}")
    print(f"Cleaned output saved to separate file:           '{output_csv}'")

    print("\nSample Output Rows:")
    preview_cols = [
        c
        for c in ["Place", "Name Variant", "Reference"]
        if c in df.columns
    ]
    print(df[preview_cols].head(10).to_string(index=False))


if __name__ == "__main__":
    split_bracket_variants_and_fix_casing()