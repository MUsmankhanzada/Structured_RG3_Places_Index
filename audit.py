import os
import re
import pandas as pd


def check_institution_for_misplaced_digits(val):
    """
    Flags numerical citations accidentally absorbed into Institution.
    Permits legitimate historical / saint name markers if any, but flags:
      - Trailing page/column citations (e.g. 'eccl. 187', 'par. eccl. 260')
      - Any multi-digit citations or digit sequences (> 1 digit or isolated numbers)
    """
    if pd.isna(val):
        return False
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return False

    # Check for trailing digits / citations at the end of the institution string
    if re.search(r"\d+\.?$", s):
        return True

    # Check for 2+ digit sequences anywhere in Institution (citations like 105, 336)
    if re.search(r"\b\d{2,}\b", s):
        return True

    # Check for single standalone numbers not attached to saint prefixes
    if re.search(r"(?<![a-zA-Z\.\-])\b\d+\b", s):
        return True

    return False


def audit_and_save_numbers(
    input_csv="ortsverzeichnis_vol3_no_references.csv",
    output_csv="flagged_rows_with_numbers_1.csv",
):
    if not os.path.exists(input_csv):
        print(f"Error: File '{input_csv}' not found.")
        return

    df = pd.read_csv(input_csv, encoding="utf-8-sig")
    print(f"Loaded '{input_csv}' with {len(df)} total rows.")

    target_columns = ["Place", "Name Variant", "Institution", "Office"]
    missing_cols = [c for c in target_columns if c not in df.columns]
    if missing_cols:
        print(f"Error: Missing column(s) in CSV: {missing_cols}")
        return

    # Check for presence of digits in text columns
    place_has_digit = df["Place"].fillna("").astype(str).str.contains(r"\d", regex=True)
    variant_has_digit = df["Name Variant"].fillna("").astype(str).str.contains(r"\d", regex=True)
    inst_has_digit = df["Institution"].apply(check_institution_for_misplaced_digits)
    office_has_digit = df["Office"].fillna("").astype(str).str.contains(r"\d", regex=True)

    # Check for empty / missing Column_num
    if "Column_num" in df.columns:
        col_num_clean = df["Column_num"].fillna("").astype(str).str.strip()
        missing_column_num = col_num_clean.eq("") | col_num_clean.str.lower().eq("nan")
    else:
        missing_column_num = pd.Series(False, index=df.index)

    # Combined mask: digits misplaced in text columns OR completely missing Column_num
    combined_mask = (
        place_has_digit
        | variant_has_digit
        | inst_has_digit
        | office_has_digit
        | missing_column_num
    )
    flagged_df = df[combined_mask].copy()

    # Track specific reasons why each row was flagged
    def identify_reasons(row):
        reasons = []
        if place_has_digit.loc[row.name]:
            reasons.append("Digit in Place")
        if variant_has_digit.loc[row.name]:
            reasons.append("Digit in Name Variant")
        if inst_has_digit.loc[row.name]:
            reasons.append("Digit in Institution")
        if office_has_digit.loc[row.name]:
            reasons.append("Digit in Office")
        if missing_column_num.loc[row.name]:
            reasons.append("Missing Column_num")
        return ", ".join(reasons)

    flagged_df["Flag_Reason"] = flagged_df.apply(identify_reasons, axis=1)

    print("\n--- Audit Summary ---")
    print(f"Total rows flagged:             {len(flagged_df)}")
    print(f" - Numbers in 'Place':          {place_has_digit.sum()}")
    print(f" - Numbers in 'Name Variant':    {variant_has_digit.sum()}")
    print(f" - Numbers in 'Institution':     {inst_has_digit.sum()}")
    print(f" - Numbers in 'Office':          {office_has_digit.sum()}")
    print(f" - Missing 'Column_num':         {missing_column_num.sum()}")

    if not flagged_df.empty:
        flagged_df.to_csv(output_csv, index=True, encoding="utf-8-sig")
        print(f"\nFlagged rows saved to: '{output_csv}'")

        print("\nSample flagged rows:")
        cols_to_show = [
            "Place",
            "Name Variant",
            "Institution",
            "Office",
            "Column_num",
            "Flag_Reason",
        ]
        for idx, row in flagged_df[cols_to_show].head(12).iterrows():
            print(
                f"  Row {idx:4d} | Reason: {row['Flag_Reason']:<35} | "
                f"Place: '{row['Place']}' | Inst: '{row['Institution']}' | ColNum: '{row.get('Column_num', '')}'"
            )
    else:
        print("\nNo anomalies found (no misplaced digits in any text column, and no missing Column_num values).")


if __name__ == "__main__":
    audit_and_save_numbers()