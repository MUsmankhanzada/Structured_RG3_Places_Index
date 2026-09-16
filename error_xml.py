#!/usr/bin/env python3
"""
export_xml_errors.py

Generates a standalone report of OCR and transcription errors
present in the canonical XML files versus the correct CSV records.
"""

import pandas as pd

XML_ERRORS_DATA = [
    {
        "Section": "F",
        "ort_id": "10300670",
        "Correct_CSV_Place": "Flandern",
        "Corrupted_XML_Place": "Flandem",
        "Error_Type": "OCR ligature misread ('rn' -> 'm')",
    },
    {
        "Section": "F",
        "ort_id": "10300695",
        "Correct_CSV_Place": "Frauenchiemsee",
        "Corrupted_XML_Place": "Frauenchiernsee",
        "Error_Type": "OCR ligature misread ('m' -> 'rn')",
    },
    {
        "Section": "H",
        "ort_id": "10300905",
        "Correct_CSV_Place": "Halicz",
        "Corrupted_XML_Place": "HaUcz",
        "Error_Type": "OCR case/character misread ('li' -> 'U')",
    },
    {
        "Section": "K",
        "ort_id": "10301156",
        "Correct_CSV_Place": "Klein-Fischlingen",
        "Corrupted_XML_Place": "Klein-Fischhngen",
        "Error_Type": "OCR character misread ('li' -> 'h')",
    },
    {
        "Section": "K",
        "ort_id": "10301195",
        "Correct_CSV_Place": "Kulmbach",
        "Corrupted_XML_Place": "Kuhnbach",
        "Error_Type": "OCR character misread ('m' -> 'hn')",
    },
    {
        "Section": "L",
        "ort_id": "10301294",
        "Correct_CSV_Place": "Lobeda",
        "Corrupted_XML_Place": "Iobeda",
        "Error_Type": "OCR capital letter misread ('L' -> 'I')",
    },
    
    {
        "Section": "N",
        "ort_id": "10301564",
        "Correct_CSV_Place": "Nicopolis",
        "Corrupted_XML_Place": "Nicopohs",
        "Error_Type": "OCR character misread ('li' -> 'h')",
    },
    {
        "Section": "S",
        "ort_id": "10302157",
        "Correct_CSV_Place": "Sulzberg, Val di Sole",
        "Corrupted_XML_Place": "Sulzberg, V a l di Sole",
        "Error_Type": "Spaced typesetting / OCR whitespace artifact ('Val' -> 'V a l')",
    },
    {
        "Section": "T",
        "ort_id": "10302196",
        "Correct_CSV_Place": "Tegernheim",
        "Corrupted_XML_Place": "Tegemheim",
        "Error_Type": "OCR ligature misread ('rn' -> 'm')",
    },
    {
        "Section": "T",
        "ort_id": "10302238",
        "Correct_CSV_Place": "Tongern",
        "Corrupted_XML_Place": "Tongem",
        "Error_Type": "OCR ligature misread ('rn' -> 'm')",
    },
    {
        "Section": "V",
        "ort_id": "10302355",
        "Correct_CSV_Place": "Vilich",
        "Corrupted_XML_Place": "Vihch",
        "Error_Type": "OCR character misread ('li' -> 'h')",
    },
    {
        "Section": "V",
        "ort_id": "10302361",
        "Correct_CSV_Place": "Villingen",
        "Corrupted_XML_Place": "Vilhngen",
        "Error_Type": "OCR character misread ('li' -> 'h')",
    },
    {
        "Section": "W",
        "ort_id": "10302442",
        "Correct_CSV_Place": "Warnow",
        "Corrupted_XML_Place": "Wamow",
        "Error_Type": "OCR ligature misread ('rn' -> 'm')",
    },
]

OUTPUT_CSV = "xml_ocr_errors.csv"

df_errors = pd.DataFrame(XML_ERRORS_DATA)
df_errors.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
print(f"Exported {len(df_errors)} XML error records to: '{OUTPUT_CSV}'")