# Historical Gazetteer (Ortsverzeichnis Vol. 3) Extraction & Standardization

An end-to-end processing pipeline to extract, repair, standardize, and audit historical gazetteer entries from double-column scans using multimodal LLM vision extraction and rule-based parsing.

---

## 1. Prerequisites & Environment Setup

Ensure Python 3.10+ is installed.

### Clone Repository & Create Virtual Environment
```bash
git clone <https://github.com/MUsmankhanzada/Structured_RG3_Places_Index.git>
cd <Structured_RG3_Places_Index>

python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

---

## 1) Environment & API Setup

### Step A: Create and Activate Virtual Environment
```bash
python -m venv venv
source venv/bin/activate
# On Windows use: venv\Scripts\activate
```

### Step B: Install Requirements
Install all core dependencies:
```bash
pip install pandas opencv-python openai python-dotenv
```

### Step C: Configure API Credentials
Create a `.env` file in the root directory:
```env
ACADEMIC_CLOUD_API_KEY=your_api_key_here
ACADEMIC_CLOUD_BASE_URL=[https://chat-ai.academiccloud.de/v1](https://chat-ai.academiccloud.de/v1)
MODEL_NAME=qwen3-omni-30b-a3b-instruct
```

Ensure sensitive credentials are excluded from version control:
```bash
echo ".env" >> .gitignore
echo "venv/" >> .gitignore
```

---

## 2) Step-by-Step Execution Pipeline

Run the scripts in the following order:

### Step 1: Raw Multimodal Extraction
Extracts verbatim text columns from scanned double-column index pages:
```bash
python grab_place.py
```
- **Input:** Scanned page images (`He 6481 (3_0xxx)...`)
- **Output:** `ortsverzeichnis_vol3_raw_final.csv` (with progress saved to `ortsverzeichnis_vol3_raw_checkpoint.csv`)

### Step 2: Post-LLM Cleaning & Anomaly Repair
Repairs character encodings, merges continuation lines, fixes known scan glitches, re-stitches split entries (e.g., *Nürnberg*, *Traubach*), and removes alphabetical repetition loops:
```bash
python fix_llm_output.py
```
- **Input:** `ortsverzeichnis_vol3_raw_final.csv`
- **Output:** `ortsverzeichnis_vol3_raw_final_fixed.csv`

### Step 3: Structural Field Extraction & Reference Splitting
Parses raw entries into discrete columns (`Place`, `Name Variant`, `Institution`, `Office`, `Column_num`, `Reference`), merges parish records, applies entity fixes, and separates cross-references from substantive entries:
```bash
python extract_and_structure.py
```
- **Inputs:** `ortsverzeichnis_vol3_raw_final_fixed.csv`
- **Outputs:**
  - `ortsverzeichnis_vol3_structured_par_fixed.csv` (Complete structured dataset)
  - `ortsverzeichnis_vol3_no_references.csv` (Substantive entries only)
  - `ortsverzeichnis_vol3_references_only.csv` (Cross-references only)
  - `flagged_missing_column_num_1.csv` (Initial check for missing citations)

### Step 4: Reference Standardization
Splits bracketed name variants out of place strings and normalizes irregular uppercase OCR casing:
```bash
python fix_reference.py
```
- **Input:** `ortsverzeichnis_vol3_references_only.csv`
- **Output:** `ortsverzeichnis_vol3_references_only_cleaned.csv`

### Step 5: Substantive Data Audit
Audits substantive entries for misplaced numbers in text columns or missing column citations:
```bash
python audit_pipeline.py
```
- **Input:** `ortsverzeichnis_vol3_no_references.csv`
- **Output:** `flagged_rows_with_numbers_1.csv`
