# Historical Gazetteer (Ortsverzeichnis Vol. 3) Extraction & Standardization

An end-to-end processing pipeline to extract, repair, standardize, and audit historical gazetteer entries from double-column scans using multimodal LLM vision extraction and rule-based parsing.

**Current output:** 3,543 substantive rows, 3,516 aligned to authority `ort_id`.

---

## 1) Environment & API Setup

### Step A: Clone Repository & Set Up Virtual Environment
Ensure Python 3.10+ is installed.

```bash
git clone https://github.com/MUsmankhanzada/Structured_RG3_Places_Index.git
cd Structured_RG3_Places_Index

python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate
```

### Step B: Install Dependencies
Install all required libraries directly via `pip`:
```bash
pip install pandas opencv-python openai python-dotenv
```

### Step C: Configure API Credentials
Create a `.env` file in the project root:
```env
ACADEMIC_CLOUD_API_KEY=your_api_key_here
ACADEMIC_CLOUD_BASE_URL=https://chat-ai.academiccloud.de/v1
MODEL_NAME=qwen3-omni-30b-a3b-instruct
```

Ensure local credentials and environment folders remain excluded from version control:
```bash
echo ".env" >> .gitignore
echo "venv/" >> .gitignore
```

---

## 2) Step-by-Step Execution Pipeline

Run the pipeline scripts in the exact sequence outlined below.

| Step | Script | Output |
|---|---|---|
| 1 | `grab_place.py` | `ortsverzeichnis_vol3_raw_final.csv` |
| 2 | `fix_llm_output.py` | `ortsverzeichnis_vol3_raw_final_fixed.csv` |
| 3 | `extract_and_structure.py` | structured / no_references / references_only |
| 4 | `fix_reference.py` | `..._references_only_cleaned.csv` |
| 5 | `audit_pipeline.py` | audit flags |
| 6 | `xml_mapping.py` → `fix_spellings.py` → `xml_mapping.py` | authority-aligned dataset |

---

### Step 1: Raw Multimodal Vision Extraction
Processes double-column scanned page images, applies automatic margin cropping, vertical split-line detection, and prompts the multimodal vision LLM (`qwen3-omni-30b-a3b-instruct`) to transcribe single headword records with line continuations.
```bash
python grab_place.py
```
- **Input:** Scanned double-column index pages (`He 6481 (3_0xxx)...`)
- **Output:** `ortsverzeichnis_vol3_raw_final.csv` (with incremental checkpoints saved to `ortsverzeichnis_vol3_raw_checkpoint.csv`)

---

### Step 2: Post-LLM Cleaning, Anomaly Repair & Deduplication
Addresses character encodings, merges continuation lines, fixes LLM transcription corruptions, repairs broken multi-line entries, and eliminates transcription loop repetitions.
```bash
python fix_llm_output.py
```
- **Input:** `ortsverzeichnis_vol3_raw_final.csv`
- **Output:** `ortsverzeichnis_vol3_raw_final_fixed.csv`

#### Discovery & Verification Workflow
Anomalies were systematically surfaced by scanning intermediate outputs for two flags:
1. **Misplaced digits in text fields** (`Place`, `Name Variant`, or `Office`).
2. **Empty or missing values in `Column_num`** for records that were not cross-references.

Whenever a record was flagged, the physical hard-copy volume (*Repertorium Germanicum*, Vol. 3 Ortsverzeichnis) was consulted to inspect the original layout, punctuation, and column boundaries. Concrete corrections were then coded into `fix_llm_output.py`:

* **Alphabetical Restart Loops (LLM Deduplication):**
  Due to overlapping image processing batches or prompt resets across page slices, the model repeatedly broke its strict alphabetical progression (jumping from a `B` headword directly back to `A`, e.g., `Benhusen` $\rightarrow$ `Aachen`). The script identifies this inversion index and traces forward until the loop rejoins where the first progression ended, pruning duplicate rows while maintaining alphabetical order.
* **Entries Split Across Multiple Rows:**
  Certain multi-line entries spanning line breaks or column bottoms were read as independent entries by the model:
  * *Nürnberg*: Entry 1 (`Nürnberg (Nurembergh, Nurembergen.`) and Entry 2 (`Bamberg. dioc.) capel. novi hosp. paup. 159 297...`) were merged into a single parenthesized diocesan record.
  * *Traubach*: Split across `Traubach (Grafen- oder Holz-Tr.?` and `Trawpach Ratisp. dioc.) par. eccl. 395.` — consolidated into one continuous raw record.
* **Unclosed Parentheses & Delimiter Fusion:**
  * The multimodal LLM occasionally omitted the closing parenthesis `)` terminating the alternate name variant or diocese block (e.g., in *Balsamgau*, *Conneux*, and *Kurzelow*), causing subsequent institutional roles to bleed into text columns. The script restores missing brackets before structural parsing.
  * In fused cross-references such as `Vekingenv. Vechingen.`, the model omitted the space before the lowercase `v.`, preventing the cross-reference rule from triggering. The script unbinds these into `Vekingen v. Vechingen.`.
  * Truncated tail citations (such as missing civil citations at the end of large metropolitan entries like *Mainz*) were verified against the printed text and stitched back onto the entry.
* **Inverted Syntax (Numbers Before Office/Role):**
  In cases where the transcribed text inverted standard syntax (e.g., numbers placed before roles such as `provincia: 23; 105 (dom. s. Antoni)...` or `: 46 prepos.`), pre-processing rules re-order tokens into canonical `<Role> <Column>` syntax.
* **Block Substitutions for Scrambled Scans:**
  Specific damaged or heavily corrupted sequences (e.g., *St. Florian* / F-series, *Metz*, *Rom*, *Samland*, and *Solec*) were cross-referenced against the physical book and replaced with clean, verbatim transcriptions.

---

### Step 3: Structural Field Extraction & Reference Splitting
Parses raw entries into normalized database columns (`Place`, `Name Variant`, `Diocese`, `Institution`, `Office`, `Column_num`, `Reference`), consolidates orphan parish (`par.`) records, applies specialized role overrides, strips lone alphabet header rows, and separates cross-references from substantive records.
```bash
python extract_and_structure.py
```
- **Input:** `ortsverzeichnis_vol3_raw_final_fixed.csv`
- **Outputs:**
  - `ortsverzeichnis_vol3_structured_par_fixed.csv` (Complete structured dataset)
  - `ortsverzeichnis_vol3_no_references.csv` (Substantive entries with citations)
  - `ortsverzeichnis_vol3_references_only.csv` (Cross-reference entries: `Place` + `Reference` only)
  - `flagged_missing_column_num_1.csv` (Audit log of non-reference records missing column numbers)

#### Field Parsing Engine & Case Handling
The extraction script applies specialized parsing cascades verified against physical volume typography to handle common structures as well as edge cases:

* **Frequent Case 1: Standard Hierarchy with Colon & Semicolon Splitting**
  * *Raw:* `Frankfurt a. M. (...) eccl. s. Bartholomei: prepos. 95 273; decan. 22; scholast. 114; can. 75 137.`
  * *Resolution:* The headword extractor separates `Place`, `Name Variant`, and `Diocese`. The body parser identifies institution boundaries via colons (`:`), splitting child roles on semicolons (`;`) and isolating page numbers into discrete rows with shared parent institution metadata.
* **Frequent Case 2: Multi-Row Parish (`par.`) Consolidation**
  * *Raw:* When the LLM transcribed `par.` and `eccl.` as separate chunks, initial parsing yielded an orphan office row (`Office: par.`) followed by a bare institution (`Institution: eccl. s. Petri`).
  * *Resolution:* `merge_par_records()` scans sequentially and rolls orphan `par.` tokens into the subsequent institution row (`Institution: par. eccl. s. Petri`), eliminating duplicate rows and empty column artifacts.
* **Frequent Case 3: Flat Sequence Without Explicit Colons**
  * *Raw:* `Rom (...) domus 25. civit. 81 87 207 288 307 336.`
  * *Resolution:* Semicolon-less and colon-less blocks are segmented using period-boundary lookaheads (`(?<=\d)\s*\.\s+(?=[a-z])`). Recognized prefixes in `PERSON_OR_ROLE_PREFIXES` are mapped directly to `Office` without inventing phantom institutions.
* **Rare Case 1: Complex Multi-Entry Entity Without Headword Parentheses (*Pisa*)**
  * *Raw:* `Pisa concilium 8 16 29 39 105 171 191 239 308 336 doctor 62. civit. 141.`
  * *Resolution:* Lacking standard parenthetical delimiters, the raw line was initially absorbed into a single unparsed row. `apply_structured_place_fixes()` unpacks this into three separate rows sharing the same place:
    1. `Place: Pisa | Diocese: | Institution: | Office: concilium | Column_num: 8, 16, 29, 39, 105, 171, 191, 239, 308, 336`
    2. `Place: Pisa | Diocese: | Institution: | Office: doctor    | Column_num: 62`
    3. `Place: Pisa | Diocese: | Institution: | Office: civit.    | Column_num: 141`
* **Rare Case 2: Noble Title with Trailing Columns in Place (*Toggenburg*, *Comes* series)**
  * *Raw:* `Toggenburg. com. 122.` or `[Place] comites 60 192.`
  * *Resolution:* Regex matching intercepts trailing `comes`, `com.`, `comites`, or `comitissa` attached to the headword string, moving the title to `Office` and the digits to `Column_num`.
* **Rare Case 3: Feudal Domain Roles & Harbors (*Werle*, *Villafranca*, *Amatia*)**
  * *Raw:* `Werle dominus terre 60 192.` / `Villafranca portus 334.` / `Amatia advocatus 61.`
  * *Resolution:* Domain titles (`dominus terre`), harbor indicators (`portus`), and advocacy roles (`advocatus`) are caught by expanded prefix lists and routed to their respective `Institution` or `Office` fields instead of being treated as part of the place name.
* **Rare Case 4: Editorial Annotations in Diocesan Brackets**
  * *Raw:* Entries containing uncertainty flags like `(?!) dioc.` or `(?) dioc.` (e.g., `Münster (!)`).
  * *Resolution:* Nested matching distinguishes editorial question/exclamation marks inside diocesan designators from closing parentheses, preventing premature truncation of `Name Variant`.
* **Stray Alphabet Header Pruning:**
  * Single/double letter section dividers (e.g., `D`, `G`, `H`, `I J`, `O`) that survived raw cleaning are pruned by `remove_alphabet_border_rows()` if all institutional, role, and column fields are blank.

#### Column-Assignment Corrections (Audit Round 2)

A follow-up audit of `ortsverzeichnis_vol3_no_references_mapped.csv` surfaced four systematic misassignments, all since patched in `extract_and_structure.py`.

* **OCR Variants of `eccl.` Misfiled as Office (22 rows)**
  * *Raw:* `Kreussen (Kreusen, Bamberg. dioc.) par. ecl. 103.` / `Metz (Meten.) par. ecc. s. Gangulphi 41 46.`
  * *Problem:* `INSTITUTION_PREFIXES` listed `eccl.` and `par. eccl.` but not the scanned variants. Institution-bearing blocks therefore fell through to `Office`, leaving `Institution` **empty** for 22 rows — most heavily *Metz* (6 rows), plus *Krakau*, *Kralowitz*, *Krems*, *Kreussen*, *Kreuznach*, *Kronenberg*, *Kronmetz*, *Kröpelin*, *Krut*, *Zwentendorf*. Across the file `ecc.` occurs 30×, `ecl.` 20×, bare `eccl` 3×.
  * *Resolution:* `INSTITUTION_PREFIXES` extended with `ecc.`, `ecl.`, `eccl`, `par. ecc.`, `par. ecl.`, `par ecl.`, `par eccl.`, plus `secul. eccl.`, `filial. eccl.`, `libera capel.`, `priorat.`.
* **Stray Leading Period in `Office` (6 rows)**
  * *Raw:* `Cittá di Castello (Ciuitascastelli). ep. 63.`
  * *Problem:* `body` was sliced immediately after the closing parenthesis, so the separating period survived and the first block parsed as `Office: '. ep.'`. Only the *first* block of an entry was affected, because `split_into_structural_blocks()` consumes later separators — hence *Dänemark* showed `. rex` but clean `regina` and `regnum`. Also hit *Fano*, *Hennegau*, *Neapel*, *Nebbio*.
  * *Resolution:* `body = text[matching_close_idx + 1:].lstrip(". ").strip()`.
* **`s. a.` (siehe auch) Cross-References Parsed as an Office (1 row)**
  * *Raw:* `Duurstede (Du[e]rsteden, Traiect. dioc.) dominus 368. civit. 357. s. a. Wijk.`
  * *Problem:* `parse_place_header()` recognized `v.` but not `s. a.`, so the see-also clause became `Office: 's. a. Wijk'` — the **only row in the file with no `Column_num`**, which is what surfaced it.
  * *Resolution:* A new Rule 1b strips a trailing `s. a. <Target>`, returns it as `Reference`, and re-parses the text in front of it.
  * *Follow-on fix:* unlike a pure `Place v. Target.` entry, a see-also entry still carries a **body**. The pipeline's `if cross_ref:` branch discarded `body` outright, which silently destroyed Duurstede's two substantive rows (`dominus 368`, `civit. 357`). That branch now emits the body records first with an empty `Reference`, then a single row carrying the reference — so the entry contributes 2 rows to `no_references` and 1 to `references_only`.
* **OCR Line-Break Hyphens (3 rows)**
  * *Raw:* `Thimonis- uilla`, `Therheynrix- kinder`, `Nidder- raitenow` in `Name Variant`.
  * *Resolution:* `rejoin_ocr_linebreaks()` runs first inside `patch_special_raw_entries()`. The join is restricted to lowercase-to-lowercase with a negative lookahead for `oder|und|bzw|od`, so genuine German compound ellipses survive untouched — notably `Grafen- oder Holz-Tr.? Trawpach`, which has exactly the same shape and must **not** be joined.

#### Known Remaining Cases

Five rows carry institutional text in `Office` with `Institution` empty, because the string genuinely *begins* with an office and only mentions the church later. Prefix matching cannot split these; they need structured overrides or a mid-string rule.

| Place | Office | Column |
|---|---|---|
| Elsass | `bona eccl.` | 188 |
| Mecheln | `preb. de Zollaer in eccl. s. Rumoldi` | 45 |
| Rottweil | `curia et par. eccl. in Arnoldshof (…)` | 328 |
| Toulouse | `aep. et capit. eccl.` | 336 |
| Wiemeringhausen | `additamentum eccl. Padeb.` | 363 |

---

### Step 4: Reference Standardization
Cleans the isolated cross-reference dataset by splitting bracketed alternate spelling variants into `Name Variant` (e.g., `Aldensalen. (Aldenzalen)` $\rightarrow$ Place: `Aldensalen`, Variant: `Aldenzalen`) and correcting irregular uppercase casing generated by the LLM (e.g., `YsonTIUS` $\rightarrow$ `Ysontius`, `ISONZO` $\rightarrow$ `Isonzo`).
```bash
python fix_reference.py
```
- **Input:** `ortsverzeichnis_vol3_references_only.csv`
- **Output:** `ortsverzeichnis_vol3_references_only_cleaned.csv`

> **Worth re-checking after the `s. a.` patch.** Any entry in this file that carries a trailing `s. a.` with content in front of it had its body rows silently dropped in earlier runs — that was exactly the Duurstede failure mode. Scan `references_only` for `s. a.` and confirm each such place also appears in `no_references` with its citations intact.

---

### Step 5: Substantive Data Audit
Performs final quality control on the substantive file (`ortsverzeichnis_vol3_no_references.csv`). This step serves as the definitive verification pass to make sure that no text columns (`Place`, `Name Variant`, `Office`) contain misplaced numbers and that every single entry has its corresponding `Column_num` citation properly associated with it. Any remaining anomalies are flagged and saved for inspection.
```bash
python audit_pipeline.py
```

#### Invariants Checked

| Check | Expected |
|---|---|
| Leading-period values in `Office` | 0 |
| `s. a.` text in `Office` | 0 |
| Rows with empty `Column_num` | 0 |
| `Institution` empty while `Office` is institutional | 5 (documented above) |
| Duplicate rows | 0 |
| Malformed `Column_num` | 0 |
| `Diocese` values not ending in `dioc.` | 0 |
| Digits in `Place` | 0 |
| Un-rejoined hyphen breaks | 1 (`Grafen- oder …`, intentional) |

> **Note on `Column_num`.** Parenthesized citations such as `(233 345)` in the two *Zürich* rows are preserved deliberately by `format_column_numbers()` and are not malformed.

> **Note on empty `Institution` *and* `Office`.** Seven rows legitimately have both blank — they are countries and regions (*Deutschland*, *Italien*, *Kärnten*, *Livland*, *Lombardei*, *Preussen*, *Russland*) whose citations refer to the territory itself.

---

### Step 6: Headword Alignment & Spelling Normalization

To benchmark our extracted dataset against authority gazetteer records, we cross-referenced `ortsverzeichnis_vol3_no_references.csv` against digital place index XML files (`orte_rg3_<letter>.xml`, sections A–Z, excluding J) created by an external authority project.

First, we executed the initial XML mapping audit script to scan all letter sections and surface headword mismatches between the datasets:

```bash
python xml_mapping.py
```
Running this preliminary string matching revealed that minor OCR/LLM spelling variations prevented matching against canonical XML headwords. Every mismatch was cross-checked directly against the physical hard-copy volume (Repertorium Germanicum, Vol. 3) to verify historical accuracy and determine whether the CSV or the XML retained the true spelling.

Identified instances where OCR/LLM extraction misread historical characters or spellings, including:

- `Crailheim` → `Crailsheim`
- `Patschau` → `Patschkau`
- `Belley` → `Bellelay`
- `Katzenelnbogen` → `Katzenellnbogen`

Once the true historical spellings were established, the verified headword alignments were applied directly to the substantive CSV using:
```bash
python fix_spellings.py
```
Finally, we re-ran the XML mapping pipeline to produce the completed, verified dataset with all aligned authority IDs populated:
```bash
python xml_mapping.py
```

> **Ordering matters.** `fix_spellings.py` must run *between* the two `xml_mapping.py` passes. Skipping it costs roughly 40 alignments, because unnormalized headwords — `Belley`, `Crailheim`, `Bönsell`, `Berghem`, `Cittá di Castello` — no longer match their authority entries. The symptom is a sudden drop in populated `ort_id` with no change in row count.

---
