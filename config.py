"""Shared constants (match Rater_A/B sheets in BDD_vignette_templates_20261122_V1_claude.xlsx)."""

APP_VERSION = "V1"
APP_DATE = "2026-11-22"

CATS = ["BDD", "Non-BDD", "ข้อมูลไม่พอ"]
CATS2 = ["BDD", "Non-BDD"]
INSIGHT = ["good/fair", "poor", "absent/delusional"]
RATERS = ["A", "B"]
ORDER_SEED = 20261122
TARGET_PER_CLASS = 75

# Short labels follow the Excel template; long text is a paraphrase of DSM-5-TR (not verbatim).
CRITERIA = {
    "a": ("A: หมกมุ่นกับ defect ที่ไม่มี/เล็กน้อย",
          "หมกมุ่นกับข้อบกพร่องของรูปลักษณ์ที่ผู้อื่นมองไม่เห็นหรือเห็นเพียงเล็กน้อย"),
    "b": ("B: พฤติกรรม/ความคิดซ้ำ ๆ",
          "มีพฤติกรรมซ้ำ ๆ (เช่น ส่องกระจก ปกปิด แกะผิว ขอความมั่นใจ) หรือการกระทำในใจ "
          "(เช่น เปรียบเทียบกับผู้อื่น) จากความกังวลนี้"),
    "c": ("C: ทุกข์ใจ/เสียหน้าที่อย่างมีนัยสำคัญ",
          "ทำให้ทุกข์ใจอย่างมีนัยสำคัญ หรือบกพร่องด้านสังคม การงาน หรือด้านสำคัญอื่น"),
    "d": ("D: ไม่ใช่ eating disorder",
          "ความหมกมุ่นไม่ได้อธิบายได้ดีกว่าด้วยความกังวลเรื่องไขมัน/น้ำหนักในผู้ที่เข้าเกณฑ์ "
          "eating disorder (☑ = ผ่านข้อนี้)"),
}

# Column names expected in the Blueprint sheet
BP_COLS = {
    "vid": "ID",
    "cls": "Class (blueprint)",
    "stratum_code": "Stratum code",
    "area": "บริเวณที่กังวล",
    "set_role": "หลัก/สำรอง",
    "text": "Vignette (ข้อความเต็ม)",
}
