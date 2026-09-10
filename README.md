# Historical Gazetteer (Ortsverzeichnis Vol. 3) Extraction & Standardization

An end-to-end processing pipeline to extract, repair, standardize, and audit historical gazetteer entries from double-column scans using multimodal LLM vision extraction and rule-based parsing.

---

## 1) Environment & API Setup

### Step A: Clone Repository & Set Up Virtual Environment
Ensure Python 3.10+ is installed.

```bash
git clone [https://github.com/MUsmankhanzada/Structured_RG3_Places_Index.git](https://github.com/MUsmankhanzada/Structured_RG3_Places_Index.git)
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
ACADEMIC_CLOUD_BASE_URL=[https://chat-ai.academiccloud.de/v1](https://chat-ai.academiccloud.de/v1)
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

---

### Step 4: Reference Standardization
Cleans the isolated cross-reference dataset by splitting bracketed alternate spelling variants into `Name Variant` (e.g., `Aldensalen. (Aldenzalen)` $\rightarrow$ Place: `Aldensalen`, Variant: `Aldenzalen`) and correcting irregular uppercase casing generated by the LLM (e.g., `YsonTIUS` $\rightarrow$ `Ysontius`, `ISONZO` $\rightarrow$ `Isonzo`).
```bash
python fix_reference.py
```
- **Input:** `ortsverzeichnis_vol3_references_only.csv`
- **Output:** `ortsverzeichnis_vol3_references_only_cleaned.csv`

---

### Step 5: Substantive Data Audit
Performs final quality control on the substantive file (`ortsverzeichnis_vol3_no_references.csv`). This step serves as the definitive verification pass to make sure that no text columns (`Place`, `Name Variant`, `Office`) contain misplaced numbers and that every single entry has its corresponding `Column_num` citation properly associated with it. Any remaining anomalies are flagged and saved for inspection.
```bash
python audit_pipeline.py
```
- **Input:** `ortsverzeichnis_vol3_no_references.csv`
- **Output:** `flagged_rows_with_numbers_1.csv`
