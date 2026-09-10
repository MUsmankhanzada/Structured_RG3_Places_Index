import os
import pandas as pd


def audit_and_save_numbers(
    input_csv="ortsverzeichnis_vol3_no_references.csv",
    output_csv="flagged_rows_with_numbers_1.csv",
):
    if not os.path.exists(input_csv):
        print(f"Error: File '{input_csv}' not found.")
        return

    df = pd.read_csv(input_csv, encoding="utf-8-sig")
    print(f"Loaded '{input_csv}' with {len(df)} total rows.")

    target_columns = ["Place", "Name Variant", "Office"]
    missing_cols = [c for c in target_columns if c not in df.columns]
    if missing_cols:
        print(f"Error: Missing column(s) in CSV: {missing_cols}")
        return

    # Check for presence of digits in target text columns
    place_has_digit = df["Place"].fillna("").astype(str).str.contains(r"\d", regex=True)
    variant_has_digit = df["Name Variant"].fillna("").astype(str).str.contains(r"\d", regex=True)
    office_has_digit = df["Office"].fillna("").astype(str).str.contains(r"\d", regex=True)

    # Check for empty / missing Column_num
    if "Column_num" in df.columns:
        col_num_clean = df["Column_num"].fillna("").astype(str).str.strip()
        missing_column_num = col_num_clean.eq("") | col_num_clean.str.lower().eq("nan")
    else:
        missing_column_num = pd.Series(False, index=df.index)

    # Combined mask: digits misplaced in text columns OR completely missing Column_num
    combined_mask = place_has_digit | variant_has_digit | office_has_digit | missing_column_num
    flagged_df = df[combined_mask].copy()

    # Track specific reasons why the row was flagged
    def identify_reasons(row):
        reasons = []
        if place_has_digit.loc[row.name]:
            reasons.append("Digit in Place")
        if variant_has_digit.loc[row.name]:
            reasons.append("Digit in Name Variant")
        if office_has_digit.loc[row.name]:
            reasons.append("Digit in Office")
        if missing_column_num.loc[row.name]:
            reasons.append("Missing Column_num")
        return ", ".join(reasons)

    flagged_df["Flag_Reason"] = flagged_df.apply(identify_reasons, axis=1)

    print("\n--- Audit Summary ---")
    print(f"Total rows flagged:             {len(flagged_df)}")
    print(f" - Numbers in 'Place':           {place_has_digit.sum()}")
    print(f" - Numbers in 'Name Variant':    {variant_has_digit.sum()}")
    print(f" - Numbers in 'Office':          {office_has_digit.sum()}")
    print(f" - Missing 'Column_num':         {missing_column_num.sum()}")

    if not flagged_df.empty:
        flagged_df.to_csv(output_csv, index=True, encoding="utf-8-sig")
        print(f"\nFlagged rows saved to: '{output_csv}'")

        print("\nSample flagged rows:")
        cols_to_show = ["Place", "Name Variant", "Office", "Column_num", "Flag_Reason"]
        for idx, row in flagged_df[cols_to_show].head(10).iterrows():
            print(
                f"  Row {idx:4d} | Reason: {row['Flag_Reason']:<35} | "
                f"Place: '{row['Place']}' | ColNum: '{row.get('Column_num', '')}'"
            )
    else:
        print("\nNo anomalies found (no misplaced digits and no missing Column_num values).")


if __name__ == "__main__":
    audit_and_save_numbers()