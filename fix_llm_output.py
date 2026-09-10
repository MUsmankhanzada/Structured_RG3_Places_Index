#!/usr/bin/env python3
"""
fix_llm_output.py

Consolidated pipeline to repair raw OCR/LLM outputs for the historical
gazetteer (Ortsverzeichnis Vol. 3):
  1. Encoding/mojibake normalization & quotation mark stripping.
  2. Multi-line continuation stitching based on capitalization.
  3. Context-targeted block replacements for corrupted scan/extraction sequences.
  4. Concatenation of truncated tails (e.g., Mainz citations).
  5. Multi-line split repairs (e.g., Nürnberg, Traubach).
  6. Removal of alphabetical restart loops (B -> A repeated entries).
  7. Fused cross-reference corrections (e.g., Vekingenv. -> Vekingen v.).
  8. Removal of stray header artifacts and hallucinated/misplaced entries.
"""

import os
import re
from pathlib import Path
import pandas as pd


# ==============================================================================
# 1. STRING CLEANING & NORMALIZATION UTILITIES
# ==============================================================================

def fix_mojibake_str(val):
    """
    Re-encodes Latin-1 strings mistakenly parsed from UTF-8 bytes.
    """
    if isinstance(val, str):
        try:
            return val.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return val
    return val


def remove_quotes(val):
    """
    Strips leading and trailing quotes from text fields while leaving
    internal quotation marks intact.
    """
    if isinstance(val, str):
        return val.strip().strip('"').strip("'").strip()
    return val


def starts_with_uppercase(text):
    """
    Checks the first alphabetical character of a string:
      - True  -> Uppercase (indicates a new headword entry)
      - False -> Lowercase (continuation of the preceding record)
    """
    if pd.isna(text):
        return False
    text = str(text).strip()
    if not text:
        return False
    for char in text:
        if char.isalpha():
            return char.isupper()
    return False


def get_headword_key(raw_text):
    """
    Extracts the uppercase primary alphabetical headword for alphabetical order audits.
    """
    if not isinstance(raw_text, str):
        return ""
    cleaned = re.sub(r"^[\(\[\"\'\s]+", "", raw_text.strip())
    match = re.match(r"^([a-zA-ZäöüÄÖÜß]+)", cleaned)
    if match:
        return match.group(1).upper()
    return ""


# ==============================================================================
# 2. CONTINUATION & SPLIT ROW MERGING
# ==============================================================================

def merge_continuation_lines(df, text_col):
    """
    Merges rows that begin with a lowercase character into the prior row.
    """
    merged_rows = []

    for _, row in df.iterrows():
        text = row[text_col]
        if pd.isna(text):
            continue
        text = str(text).strip()
        if not text:
            continue

        if starts_with_uppercase(text):
            new_row = row.copy()
            new_row[text_col] = text
            merged_rows.append(new_row)
        else:
            if not merged_rows:
                new_row = row.copy()
                new_row[text_col] = text
                merged_rows.append(new_row)
            else:
                merged_rows[-1][text_col] = (
                    str(merged_rows[-1][text_col]).strip() + " " + text
                )

    clean_df = pd.DataFrame(merged_rows).reset_index(drop=True)
    return clean_df


def merge_split_raw_entries(raw_entries):
    """
    Re-joins consecutive rows that were split across OCR cell/table breaks,
    such as Nürnberg and Traubach.
    """
    merged_rows = []
    skip_next = False
    n = len(raw_entries)
    merge_count = 0

    for i in range(n):
        if skip_next:
            skip_next = False
            continue

        curr = str(raw_entries[i]).strip()
        nxt = str(raw_entries[i + 1]).strip() if i + 1 < n else ""

        # Case 1: Nürnberg split across parentheses
        if "Nürnberg" in curr and "Nurembergen." in curr and nxt.startswith("Bamberg. dioc.)"):
            combined = f"{curr} {nxt}"
            merged_rows.append(combined)
            skip_next = True
            merge_count += 1
            continue

        # Case 2: Traubach split across parentheses
        if "Traubach" in curr and "Holz-Tr.?" in curr and "Trawpach Ratisp. dioc.)" in nxt:
            combined = f"{curr} {nxt}"
            merged_rows.append(combined)
            skip_next = True
            merge_count += 1
            continue

        merged_rows.append(curr)

    if merge_count > 0:
        print(f"Merged {merge_count} split multi-line entry pair(s) (Nürnberg / Traubach).")

    return merged_rows


# ==============================================================================
# 3. REPLACEMENT BLOCKS DEFINITION
# ==============================================================================

REPLACEMENT_857 = [
    "St. Florian (de Sanctofloriano Patav. dioc.) mon. s. Floriani: prepos. 17; can. 17; capit. 17; benef. 364.",
    "Fonsdorf (Vanstorff Salzb. dioc.) par. eccl. 201 238.",
    "Fonssalutis v. Heilsbronn.",
    "Forchheim (Vorheim Bamberg. dioc.) eccl. s. Martini: can. 39 103 274.",
    "Föring (Voring Salzb. dioc.) par. eccl. s. Marie 260.",
    "Formbach (Wormpach Patav. dioc.) mon. o. s. B.: abb. 329 365.",
    "Forstenwalde v. Fürstenwalde.",
    "Fosse (Fossen. Leod. dioc.) eccl. s. Foilani: can. 154.",
]

REPLACEMENT_858 = [
    "le Fousseret (Fosseretum Ruien. dioc.) par. eccl. 325.",
    "Francia v. Frankreich.",
    "Frankenhausen (Franckenhusen Magunt. dioc.) eccl. s. Jacobi: vic. 248.",
    "Frankenstein (Frankenstein Wratisl. dioc.) par. eccl. 295.",
    "Frankenuorde v. Frankfurt a. O.",
    "Frankfurt a. M. (Fran(c)kford Magunt. dioc.) eccl. s. Bartholomei: prepos. 95 273; decan. 22; scholast. 114; can. 75 137; capit. 273; vic. 211 273 274. eccl. s. Leonardi: capit. 203. eccl. b. Marie in Monte: decan. 211 273 274; can. 211 274; capit. 273 274. eccl. bb. Marie et Georgii: decan. 203; can. 211; capit. 203; vic. 251. capel. s. Antonii 327. mon. s. Catherine Nouiopidi: alt. 85. civit. 304 337.",
    "Frankfurt a. O. (Frankenuorde Lubuc. dioc.) eccl.: alt. 324.",
    "Frankreich (Francia) rex 28 267. regnum 21 61 63 114 203 325.",
    "Frascati (Tusculan.) ep. 323.",
    "Frasslau (Fratzlauia, Frasslaw Aquil. dioc.) par. eccl. 24 25 125.",
    "Frauenaurach (Frauwenaurach Herbi-pol. dioc.) mon. o. s. A.: capel. in eccl. 87.",
]

REPLACEMENT_HAVIXBECK = [
    "Havixbeck (Haeukesbeke Monast. dioc.) par. eccl. 100 136.",
    "de Hayaualteri v. Altenmünster.",
]

REPLACEMENT_METZ = [
    "Metz (Meten.) ep. (el.) 42 46 80 85 152 201 273 322 336 342 386. ecc. : decan. 41 219 278; archidiacon. 102 283; cantor. 184 217 228 229 335; eleemosin. 23 335; primiceria 85 152 194; dign. 102 314; can. 23 41 69 85 102 134 152 180 194 212 215 217 228 229 235 252 268 314 315 316 317 335 336 398 400; capit. 41 42 46 201 228 278 342; capel. (benef.) 23 41 184 336; not. curie 219. ecc. b. Marie Rotunde: prepos. 85 194 228 229; can. 46 317 336. ecc. s. Saluatoris: prepos. 278 315 398; dign. 314; can. 314 336. ecc. s. Theobaldi e. m.: can. 46; capel. 199. ecc. s. Elamsdis (?): can. 208. par. ecc. s. Gangulphi 41 46. par. ecc. s. Gorgonii 331. par. ecc. s. Hilarii 219. par. ecc. s. Maximini 212. par. ecc. s. Simplicii 23 101. par. ecc. s. Victoris 179 229. capel. s. Galli 229. capel. noue ecc. s. Johannis 184. capel. b. Marie in domo Petri de Pairgin resp. Johannis de Velonia 184 212. mon. s. Arnulphi o. s. B. e. m.: abb. 191 283; conv. 283. mon. s. Simphoriani o. s. B. e. m.: monach. 212. mon. s. Vincentii o. s. B.: 259; abb. et conv. 184. presb. 80 204. cler. 41 42 46 87 183 184 194 202 206 210 235 320. mil. 183 184 205 283. domic. 203. opid. 106 205 212 283. laici 273.",
    "Messenberg v. Massenberg.",
    "Meyenburg (Meynborch Bremen. dioc.) castrum et capel. 253.",
    "Meysseldeck v. Meiselding.",
]

REPLACEMENT_ROM = [
    "Rom (Roma, Vrbs) eccl. s. Marie maioris: can. 336. eccl. ss. Petri et Pauli: 305. mon. s. Pauli e. m.: 306; monach. 299. priorat. s. Johannes Ierosol. 53. hosp. paup. b. Marie de Anima Theutonicorum 362. hosp. paup. in Arenula 212. domus 25. civit. 81 87 207 288 307 336.",
    "de Romaricomonte v. Remiremont.",
]

REPLACEMENT_SAMLAND = [
    "Samland (Sambien.) el. 163. eccl. 164. cler. 42 125. opid. 202.",
    "de Sanctoamerino v. St. Amerin.",
    "de Sanctoarnuale v. St. Arnual.",
    "de Sanctoaudomaro v. St. Omer.",
    "de Sanctodaniele v. St. Daniel.",
    "de Sanctodeodato v. St. Dié.",
    "de Sanctodionisio v. St. Denis, St. Dionysen.",
    "de Sanctoermachore v. Hermagor.",
    "de Sanctofloriano v. St. Florian.",
    "Sanctogallo v. St. Gallen.",
    "de Sanctolamberto v. St. Lambert.",
    "de Sanctomichaele v. St. Michel.",
    "de Sancto Michaele v. St. Mihiel.",
    "de Sanctonabore v. St. Avold.",
]

REPLACEMENT_SOLEC = [
    "Solec (Solecz Poznan. dioc.) eccl. filial. s. Adalberti 102.",
    "in Solio v. Maria Saal.",
]

REPLACEMENT_BRUBERG = [
    "Bruberg v. Brenberg.",
    "zum Bruche (de Broke Bremen. dioc.) par. eccl. 253.",
]

REPLACEMENT_HEELSPRUNNA = [
    "Heelsprunna v. Heilbronn.",
    "s’Heerhendrikskinderen (Therheynrix- kinder Traiect. dioc.) par. eccl. 311.",
]

REPLACEMENT_PORRENTRUY = [
    "Porrentruy (Ponrramtin) v. Miserach.",
    "Porta v. Pforta.",
]

MAINZ_SUFFIX = " domic. 105 359. opid. 317 376 laici 167 187 212 243 288 312. civit. 337"


# ==============================================================================
# 4. ENTRY-LEVEL PATCHING & ANOMALY RESOLUTION
# ==============================================================================

def patch_and_filter_raw_entries(raw_entries):
    """
    Applies text block replacements, missing tail additions, cross-reference 
    formatting, and prunes hallucinated duplicate loops.
    """
    new_entries = []

    for idx, raw in enumerate(raw_entries):
        s = str(raw).strip()
        if not s or s == "nan":
            continue

        # 1. Remove lone uppercase section headers (e.g. 'G')
        if s in ("G", "D", "H", "O"):
            continue

        # 2. Remove hallucinated / repeated loop headwords
        if s in ("Achen", "Aalen") or (
            s.startswith("Aemps v. Ems.") and "domic. 105 359" in s
        ):
            continue

        # 3. Remove misplaced second 'Aachen' (repetition past row 1000)
        if idx > 1000 and s.lower().startswith("aachen"):
            continue

        # 4. Fused cross-reference fix (Vekingenv. -> Vekingen v. & general case)
        if "Vekingenv." in s:
            s = s.replace("Vekingenv.", "Vekingen v.")
        else:
            s = re.sub(r"\b([a-zA-ZäöüÄÖÜß]+)v\.\s+([A-ZÄÖÜ])", r"\1 v. \2", s)

        # 5. Context-based corrupted block substitutions
        if "onsdorf (Vanstorff" in s and "St. Florian" in s:
            new_entries.extend(REPLACEMENT_857)
        elif "rancia v. Frankreich" in s or "rankenhausen" in s:
            new_entries.extend(REPLACEMENT_858)
        elif "Havixbeck" in s and "de Hayaualteri v." in s:
            new_entries.extend(REPLACEMENT_HAVIXBECK)
        elif "Metz (Meten.)" in s and "Messenberg v. Massenberg" in s:
            new_entries.extend(REPLACEMENT_METZ)
        elif "Rom (Roma, Vrbs)" in s and "de Romaricomonte v." in s:
            new_entries.extend(REPLACEMENT_ROM)
        elif "Samland (Sambien.)" in s and "de Sanctoamerino v." in s:
            new_entries.extend(REPLACEMENT_SAMLAND)
        elif "Solec (Solecz Poznan. dioc.)" in s and "in Solio v. Maria Saal." in s:
            new_entries.extend(REPLACEMENT_SOLEC)
        elif "Bruberg v. Brenberg" in s and "zum Bruche" in s:
            new_entries.extend(REPLACEMENT_BRUBERG)
        elif "Heelsprunna v. Heilbronn" in s and "s’Heerhendrikskinderen" in s:
            new_entries.extend(REPLACEMENT_HEELSPRUNNA)
        elif "Porrentruy" in s and "Porta v. Pforta" in s:
            new_entries.extend(REPLACEMENT_PORRENTRUY)
        elif (
            s.startswith("Mainz (Maguntin., Moguntin.)")
            and "baron. 95." in s
            and not s.endswith("civit. 337")
        ):
            fixed_mainz = s.rstrip(".") + "." + MAINZ_SUFFIX
            new_entries.append(fixed_mainz)
        else:
            new_entries.append(s)

    return new_entries


# ==============================================================================
# 5. ALPHABETICAL REPETITION LOOP PRUNING
# ==============================================================================

def remove_alphabetical_repetition_loop(raw_entries):
    """
    Detects where the dataset unexpectedly restarts from B... back to A...
    and slices out the entire duplicate progression until convergence.
    """
    keys = [get_headword_key(entry) for entry in raw_entries]
    restart_idx = None

    # 1. Detect where entry order jumps from B... backwards to A...
    for i in range(1, len(keys)):
        prev_k = keys[i - 1]
        curr_k = keys[i]

        if prev_k.startswith("B") and curr_k.startswith("A"):
            restart_idx = i
            print(f"\n[!] Alphabetical inversion detected at index {restart_idx}:")
            print(f"    Row {i-1}: '{raw_entries[i-1][:60]}...'")
            print(f"    Row {i}:   '{raw_entries[i][:60]}...'")
            break

    if restart_idx is None:
        # Fallback check specifically on Benhusen
        benhusen_indices = [
            i for i, entry in enumerate(raw_entries) if entry.strip().startswith("Benhusen")
        ]
        if len(benhusen_indices) >= 2:
            restart_idx = benhusen_indices[0] + 1
            print(f"Fallback check detected restart after row index {restart_idx - 1}")
        else:
            print("No alphabetical restart or duplicate loop detected.")
            return raw_entries

    # 2. Find where the repeated loop terminates
    last_valid_raw = raw_entries[restart_idx - 1]
    last_valid_key = keys[restart_idx - 1]

    loop_end_idx = None
    for j in range(restart_idx, len(keys)):
        if keys[j] == last_valid_key or raw_entries[j].split()[0] == last_valid_raw.split()[0]:
            loop_end_idx = j
            break

    # If an exact match isn't isolated, stop right before the first 'C' entry
    if loop_end_idx is None:
        for j in range(restart_idx, len(keys)):
            if keys[j].startswith("C"):
                loop_end_idx = j - 1
                break

    if loop_end_idx is not None:
        num_dropped = (loop_end_idx + 1) - restart_idx
        print("\n--- Removing Alphabetical Loop ---")
        print(f"  Start drop index: {restart_idx} ('{raw_entries[restart_idx][:50]}...')")
        print(f"  End drop index:   {loop_end_idx} ('{raw_entries[loop_end_idx][:50]}...')")
        print(f"  Total duplicate rows dropped: {num_dropped}")

        cleaned_entries = raw_entries[:restart_idx] + raw_entries[loop_end_idx + 1:]

        # Sanity check
        post_keys = [get_headword_key(e) for e in cleaned_entries]
        for m in range(1, len(post_keys)):
            if post_keys[m - 1].startswith("B") and post_keys[m].startswith("A"):
                print(f"  [Warning] Inversion still present at index {m}: '{cleaned_entries[m-1][:40]}' -> '{cleaned_entries[m][:40]}'")
                break
        else:
            print("  Alphabetical order verified: No B -> A loop remains.")

        return cleaned_entries

    print("Could not safely determine the end boundary for the duplicate block. Leaving entries intact.")
    return raw_entries


# ==============================================================================
# 6. PIPELINE EXECUTION
# ==============================================================================

def run_fix_pipeline(
    input_file="ortsverzeichnis_vol3_raw_final.csv",
    output_file="ortsverzeichnis_vol3_raw_final_fixed.csv",
):
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"Error: Input file '{input_file}' not found.")
        return

    print(f"Loading '{input_file}'...")
    df = pd.read_csv(input_file)
    print(f"Initial raw rows: {len(df)}")

    # Step 1: Repair mojibake and remove surrounding quotes
    print("Repairing encodings and trimming quotes...")
    df = df.map(fix_mojibake_str)
    df = df.map(remove_quotes)

    # Step 2: Merge lowercase continuation lines
    text_col = df.columns[0]
    print(f"Merging continuation lines on primary column '{text_col}'...")
    df_merged = merge_continuation_lines(df, text_col)
    print(f"Rows after continuation merge: {len(df_merged)}")

    # Step 3: Patch corrupted blocks, fix tails, and prune hallucinations
    print("Applying specific block corrections and removing artifacts...")
    raw_lines = df_merged[text_col].dropna().tolist()
    cleaned_entries = patch_and_filter_raw_entries(raw_lines)

    # Step 4: Re-stitch specific entries split across rows (Nürnberg / Traubach)
    print("Checking and merging multi-line split entries (Nürnberg / Traubach)...")
    reconstituted_entries = merge_split_raw_entries(cleaned_entries)

    # Step 5: Detect and remove alphabetical restart loops (B -> A inversion)
    print("Detecting and pruning alphabetical restart repetition loops...")
    deduped_entries = remove_alphabetical_repetition_loop(reconstituted_entries)

    # Step 6: Construct and save final dataframe
    final_df = pd.DataFrame(deduped_entries, columns=["raw_entry"])
    final_df = final_df.map(fix_mojibake_str)
    final_df.to_csv(output_file, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print(f"Original record count : {len(df)}")
    print(f"Final repaired count   : {len(final_df)}")
    print(f"Cleaned output saved to: '{output_file}'")


if __name__ == "__main__":
    run_fix_pipeline()