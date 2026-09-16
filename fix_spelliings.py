#!/usr/bin/env python3
"""
fix_all_spellings.py

Aligns place headword spellings in 'ortsverzeichnis_vol3_no_references.csv'
with canonical XML entries across all audited letter sections.
"""

import os
from pathlib import Path
import pandas as pd

# File path definition
CSV_PATH = "ortsverzeichnis_vol3_no_references.csv"

# Mapping: {CSV_Misspelled_Headword: Canonical_XML_Headword}
SPELLING_CORRECTIONS = {
    # Section B mismatches
    "Belley": "Bellelay",
    "Berghem": "Bergheim",
    "Besançon": "Besancon",
    "Bönsell": "Bösensell",
    "Bozanzen": "Bozanzaren",
    "Béziers": "Bèziers",

    # Section C mismatches
    "Caminiec": "Caminiecz",
    "Chézy-sur-Marne": "Chezy-sur-Marne",
    "Città di Castello": "Cittá di Castello",
    "Crailheim": "Crailsheim",
    "Crempé": "Crempe",

    # Section G mismatches
    "Gaspolthofen": "Gaspoltshofen",
    "Gavno": "Gavnö",
    "Giesenain": "Giesenhain",
    "Gimingem": "Gimingen",

    # Section H mismatches
    "Himmelsforte": "Himmelspforte",

    # Section K mismatches
    "Karburg": "Karlburg",
    "Katzenelnbogen": "Katzenellnbogen",

    # Section M mismatches
    "Marienwohld": "Marienwohlde",
    "Mittelkirchen": "Mittelnkirchen",
    "St. Mihel": "St. Mihiel",

    # Section N mismatches
    "Nieuweve": "Nieuwerve",

    # Section O mismatches
    "Olnstorff": "Olnstorf",

    # Section P mismatches
    "Patschau": "Patschkau",
    "Pferdingsleben": "Pferdtingsleben",
    "Pittersdorf": "Plittersdorf",
    "Platting": "Plattling",

    # Section R mismatches
    "Ramelsoh": "Ramelsloh",
    "Rhyner": "Rhynern",

    # Section S mismatches
    "Scharrrachbergheim": "Scharrachbergheim",
    "Schöntal": "Schönthal",

    # Section T mismatches
    "Thrandanes": "Throndanes",
    "Tuchfeld": "Tuchtfeld",

    # Section V mismatches
    "Viene": "Vienne",

    # Section W mismatches
    "Waldberghem": "Waldbergheim",
    "Willgotheim": "Willgottheim",
    "Wischedrad": "Wischehrad",
    "Wülflinghausen": "Wülfinghausen",
}


def apply_spelling_corrections(csv_path=CSV_PATH):
    path = Path(csv_path)
    if not path.exists():
        print(f"Error: File '{csv_path}' not found.")
        return

    print(f"Loading '{csv_path}'...")
    df = pd.read_csv(path, encoding="utf-8-sig")
    print(f"Total rows loaded: {len(df)}")

    # Clean temporary string view for precise whitespace-agnostic matching
    df["_place_match"] = df["Place"].fillna("").astype(str).str.strip()

    total_updated = 0
    print("\n--- Applying Corrections ---")

    for wrong_spelling, correct_spelling in SPELLING_CORRECTIONS.items():
        mask = df["_place_match"] == wrong_spelling
        count = mask.sum()

        if count > 0:
            df.loc[mask, "Place"] = correct_spelling
            print(f"  [FIXED] '{wrong_spelling}' -> '{correct_spelling}' ({count} row(s))")
            total_updated += count
        else:
            print(f"  [SKIPPED] '{wrong_spelling}' (0 matching rows found)")

    df.drop(columns=["_place_match"], inplace=True)

    # Save back to CSV with UTF-8 BOM encoding
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print("\n" + "=" * 60)
    print(f"Successfully updated {total_updated} row(s) in '{csv_path}'.")
    print("=" * 60)


if __name__ == "__main__":
    apply_spelling_corrections()