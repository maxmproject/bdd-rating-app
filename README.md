# BDD Vignette Rating App (V1 · 2026-11-22)

Web app ให้จิตแพทย์ 2 คน label vignette สังเคราะห์แบบ blind และแยกกันตามเกณฑ์ DSM-5-TR A–D
แทนชีต Rater_A / Rater_B / Kappa ใน `BDD_vignette_templates_20261122_V1_claude.xlsx`
ใช้คู่กับ protocol `BDD_LLM_protocol_short_20261122_V2_claude.docx` · **ไม่มีข้อมูลผู้ป่วยจริง**

## ผู้ใช้และสิทธิ์
| role | เห็นอะไร |
|---|---|
| `rater` (A, B) | ID + ข้อความ vignette เท่านั้น (ไม่เห็น class/stratum/ผลของอีกคน) · ลำดับสุ่มแยกต่อคน (seed คงที่) · แก้ได้จน lock |
| `pi` | นำเข้า vignette, ความคืบหน้า, κ + 95% CI, consensus, เลือกชุด 150, export Excel |

Blinding ทำฝั่ง server: หน้า rater ดึงข้อมูลผ่าน `db.vignettes_for_rater()` ซึ่งคืนแค่ `vid, text`

## ฟีเจอร์
- **ผู้ประเมิน:** checkbox A–D, Label (BDD / Non-BDD / ข้อมูลไม่พอ), Insight (เมื่อ BDD), Confidence 1–5, หมายเหตุ;
  เตือนและบังคับใส่เหตุผลเมื่อ label ไม่ตรงกับเกณฑ์ (BDD ต้องผ่าน A–D ทั้งหมด); บันทึกเวลา + จำนวนครั้งที่แก้; ปุ่ม lock เมื่อครบ
- **PI:**
  1. นำเข้าชีต `Blueprint` (เฉพาะแถวที่มีข้อความ) อัปโหลดซ้ำได้; ถ้าแก้ข้อความหลังมีคนประเมินแล้ว ระบบเตือนและให้ reset ผลเรื่องนั้น (ผลเก่าเก็บใน audit log)
  2. ความคืบหน้า + ปลด lock (ต้องใส่เหตุผล)
  3. Cohen's κ: label 3 หมวด (primary), 2 หมวด (ตัด "ข้อมูลไม่พอ"), รายเกณฑ์ A–D (exploratory);
     95% CI แบบ Wald (asymptotic SE ของ Fleiss–Cohen–Everitt 1969) และ percentile bootstrap (seed 20261122); PABAK สำหรับ 2 หมวด
  4. Consensus: เรื่องที่เห็นต่างหรือตอบ "ข้อมูลไม่พอ" แสดงผลทั้งสองคนข้างกัน → บันทึก consensus label; final label; เทียบกับ blueprint; เลือกเข้าชุด 150 (มีปุ่มเลือกอัตโนมัติ)
  5. Export Excel: Summary, Agreement, Rater_A, Rater_B, Kappa (คอลัมน์ตาม template), Blueprint_check, Audit_log
- **Audit log** ทุกการ login, บันทึก, แก้, lock/unlock, consensus

## โครงสร้างไฟล์
```
app.py            entry + login
rater_view.py     หน้าผู้ประเมิน
pi_view.py        หน้า PI (5 แท็บ)
analysis.py       รวมผล, final label, export Excel
stats_kappa.py    κ, SE (FCE 1969), bootstrap, PABAK
db.py             SQLAlchemy models (SQLite local / Postgres production)
auth.py           password hash (PBKDF2-SHA256, stdlib)
config.py         ค่าคงที่ (หมวด label, เกณฑ์, ชื่อคอลัมน์ Blueprint)
make_hash.py      สร้าง password_hash
tests/            pytest: ตรวจ κ/SE เทียบ scikit-learn + statsmodels และ flow ทั้งระบบ
```

## รันในเครื่อง (ทดสอบ)
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # แล้วแก้
python make_hash.py            # สร้าง hash ของแต่ละ password ไปใส่ใน secrets.toml
streamlit run app.py           # ถ้าไม่ตั้ง DATABASE_URL จะใช้ sqlite:///rating.db
pip install pytest scikit-learn statsmodels && pytest -q tests
```

## Deploy ขึ้น cloud (ฟรี) — ประมาณ 20 นาที
**สำคัญ:** Streamlit Community Cloud ไม่มี disk ถาวร ถ้าใช้ SQLite ข้อมูลจะหายเมื่อแอปรีสตาร์ต จึงต้องใช้ Postgres ภายนอก

1. **ฐานข้อมูล Postgres** (เลือกหนึ่ง): Supabase หรือ Neon (free tier)
   - สร้าง project → คัดลอก connection string (แบบ URI) → เปลี่ยน prefix เป็น `postgresql+psycopg2://` และต่อท้าย `?sslmode=require`
   - ตารางจะถูกสร้างอัตโนมัติเมื่อแอปรันครั้งแรก
   - หมายเหตุ: free tier บางเจ้าจะ pause project ที่ไม่มีการใช้งานนาน ให้ตรวจเงื่อนไขปัจจุบันของผู้ให้บริการ [[ตรวจ]]
2. **GitHub:** สร้าง repo แบบ **private** แล้ว push โฟลเดอร์นี้ (`.gitignore` กัน `secrets.toml` และ `*.db` ไว้แล้ว)
3. **Streamlit Community Cloud** (share.streamlit.io): New app → เลือก repo, branch, `app.py` → Advanced settings → **Secrets** วางเนื้อหาแบบ `secrets.toml.example` (DATABASE_URL + users 3 คน) → Deploy
4. ส่ง URL + username/password ให้ผู้ประเมินแต่ละคนแยกกัน (URL เปิดได้สาธารณะ แต่ต้อง login)

## ขั้นตอนใช้งานจริง
1. PI login → แท็บ 1 อัปโหลด template xlsx ที่ใส่ข้อความ vignette แล้ว → นำเข้า
2. (แนะนำ) ซ้อม calibrate ด้วย 6 ตัวอย่างในชีต Examples นอกระบบก่อน
3. Rater A, B ประเมินจนครบ → กด "ส่งผลและ lock"
4. PI ดู κ → ประชุม consensus ในแท็บ 4 → เลือกชุด 150 (75:75) → Export Excel
5. ใช้ Final label ในชีต Kappa เป็น reference standard สำหรับรัน LLM

## ข้อจำกัด / งานต่อ
- Login แบบ password ใน secrets (ไม่มี reset password ในแอป: แก้ hash ใน Secrets แล้ว reboot)
- ยังไม่มีโหมดศัลยแพทย์ตรวจความสมจริง และโหมดให้คะแนน output LLM (Se/Sp, Wilson CI, McNemar) — เพิ่มได้ใน V2
- Export Excel เป็น snapshot; backup ฐานข้อมูลด้วยปุ่ม Export เป็นระยะ หรือใช้ backup ของผู้ให้บริการ Postgres
