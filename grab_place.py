import base64
import json
import os
import re
import time
import cv2
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI, RateLimitError
import pandas as pd

# ---------------- Load Environment Variables ---------------- #
load_dotenv()

API_KEY = os.getenv("ACADEMIC_CLOUD_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("ACADEMIC_CLOUD_BASE_URL", "https://chat-ai.academiccloud.de/v1")
MODEL = os.getenv("MODEL_NAME", "qwen3-omni-30b-a3b-instruct")

if not API_KEY:
    raise ValueError(
        "API key not found. Please set 'ACADEMIC_CLOUD_API_KEY' or 'OPENAI_API_KEY' in your .env file or environment."
    )

START_PAGE = 348
END_PAGE = 411
CHECKPOINT_CSV = "ortsverzeichnis_vol3_raw_checkpoint.csv"
FINAL_CSV = "ortsverzeichnis_vol3_raw_final.csv"

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    timeout=120.0
)


def fix_mojibake_str(val):
    """
    Repairs double-encoded UTF-8 / Latin-1 string sequences (e.g., 'Ã¤' -> 'ä').
    """
    if isinstance(val, str):
        try:
            return val.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return val
    return val


def encode_and_resize(img_array, max_width=1200, jpeg_quality=85):
    """Resizes and compresses image to avoid payload timeouts."""
    h, w = img_array.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        img_array = cv2.resize(img_array, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
    _, buffer = cv2.imencode(".jpg", img_array, encode_param)
    return base64.b64encode(buffer).decode("utf-8")


def split_columns(image_path):
    """Crops running header/footer and splits column down the center vertical line."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Could not read {image_path}")

    h, w, _ = img.shape
    cropped = img[int(h * 0.05):int(h * 0.96), :]
    mid = w // 2
    return cropped[:, :mid], cropped[:, mid:]


def get_image_files(start_num=START_PAGE, end_num=END_PAGE):
    """Finds and sorts images in the current directory within range."""
    valid_extensions = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
    all_files = os.listdir(".")
    matched = []

    pattern = re.compile(r"He\s*6481\s*\(3_0(\d+)", re.IGNORECASE)

    for fname in all_files:
        if not fname.lower().endswith(valid_extensions):
            continue
        match = pattern.search(fname)
        if match:
            num = int(match.group(1))
            if start_num <= num <= end_num:
                matched.append((num, fname))

    matched.sort(key=lambda x: x[0])
    return [f[1] for f in matched]


def extract_column(column_img, col_tag, max_retries=5):
    """Extracts verbatim merged index records from a single column via OpenAI SDK."""
    b64_img = encode_and_resize(column_img)

    prompt = """Transcribe this historical index column into a JSON list of single-entry records.

Rules:
1. Every headword starting at the leftmost margin begins a separate record (e.g., "Aachen", "Aalen", "Aemps v. Ems.").
2. Indented continuation lines below a headword belong to that same headword and MUST be merged into that single string in exact reading order.
3. PRESERVE ALL ORIGINAL PUNCTUATION verbatim (colons, semicolons, periods, commas, brackets, parentheses, and page numbers).
4. Keep Latin abbreviations verbatim (e.g., 'eccl.', 'par. eccl.', 'prep.', 'dioc.', 'mon. o. s. B.').
5. Cross-references (e.g., 'Aemps v. Ems.') should be single string entries.
6. Preserve all German umlauts (Ä, Ö, Ü, ä, ö, ü, ß) and accents exactly as printed.

Return valid JSON with key "entries":
{"entries": ["Entry string 1", "Entry string 2"]}"""

    attempts = 0
    while attempts < max_retries:
        try:
            time.sleep(2.5)  # Baseline throttle

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                            }
                        ]
                    }
                ],
                temperature=0.0
            )

            raw_text = response.choices[0].message.content.strip()
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            data = json.loads(raw_text)
            return data.get("entries", [])

        except RateLimitError as e:
            print(f"\n[Rate Limit on {col_tag}] Waiting 30 seconds...")
            time.sleep(30)
            continue

        except (APIStatusError, Exception) as e:
            attempts += 1
            wait_time = 5 * attempts
            print(f"Error on {col_tag}: {e} (attempt {attempts}/{max_retries}), retrying in {wait_time}s...")
            time.sleep(wait_time)

    print(f"Skipping {col_tag} after {max_retries} failed attempts.")
    return []


def save_data(entries, output_filename):
    """Applies mojibake repair across all cells and exports with UTF-8 BOM encoding."""
    df = pd.DataFrame(entries, columns=["raw_entry"])
    df = df.map(fix_mojibake_str)
    df.to_csv(output_filename, index=False, encoding="utf-8-sig")


def main():
    images = get_image_files(START_PAGE, END_PAGE)
    print(f"Found {len(images)} images to process (3_{START_PAGE:04d} to 3_{END_PAGE:04d}).")

    all_entries = []

    # Resume from checkpoint if it exists
    if os.path.exists(CHECKPOINT_CSV):
        try:
            df_existing = pd.read_csv(CHECKPOINT_CSV, encoding="utf-8-sig")
            all_entries = df_existing["raw_entry"].dropna().tolist()
            print(f"Resuming from checkpoint with {len(all_entries)} entries already saved.")
        except Exception:
            pass

    for idx, img_path in enumerate(images, 1):
        print(f"\n[{idx}/{len(images)}] Processing: {img_path}")
        
        try:
            left_col, right_col = split_columns(img_path)
        except Exception as e:
            print(f"Error reading {img_path}: {e}")
            continue

        # Left Column
        left_entries = extract_column(left_col, f"{img_path} [Left]")
        if left_entries:
            all_entries.extend(left_entries)
            save_data(all_entries, CHECKPOINT_CSV)
            print(f"  Left: +{len(left_entries)} entries (Total: {len(all_entries)})")

        # Right Column
        right_entries = extract_column(right_col, f"{img_path} [Right]")
        if right_entries:
            all_entries.extend(right_entries)
            save_data(all_entries, CHECKPOINT_CSV)
            print(f"  Right: +{len(right_entries)} entries (Total: {len(all_entries)})")

    # Export Final CSV
    save_data(all_entries, FINAL_CSV)
    print(f"\n=======================================================")
    print(f"All images finished successfully!")
    print(f"Total raw entries: {len(all_entries)}")
    print(f"Saved final file: {os.path.abspath(FINAL_CSV)}")
    print(f"=======================================================")


if __name__ == "__main__":
    main()