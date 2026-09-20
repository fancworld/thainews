"""
ตัวช่วยบันทึก log งานที่ทำ + คำนวณค่าใช้จ่ายจริงของแต่ละ API call
================================================================
ทุกสคริปต์ใน pipeline (generate_content.py, add_audio_layer.py, assemble_video.py)
import โมดูลนี้ แล้วเรียก log_usage() ทันทีหลังยิง API แต่ละครั้งที่มีค่าใช้จ่าย
ดูสรุปทั้งคลิปได้ด้วย print_cost_summary(slug)

บันทึกไว้ที่ output/<slug>/cost_log.csv (ไฟล์เดียวต่อคลิป สะสมทุก step)
"""

import csv
import datetime
from pathlib import Path

USD_TO_THB = 36.0  # ปรับตามเรทจริง ณ วันที่ใช้งาน

# ราคาต่อหน่วยที่ใช้คำนวณ (เช็คจาก docs ทางการ ณ ก.ย. 2569 - ถ้าผ่านไปนานควรเช็คซ้ำ)
PRICING_NOTES = {
    "gpt-6-astra": "input $10 / output $50 ต่อ 1M token",
    "gpt-image-2.5-sunburst": "input $5 / output $30 ต่อ 1M image token",
    "eleven_multilingual_v2": "$0.10 ต่อ 1,000 ตัวอักษร",
    "music_v2": "$0.15 ต่อนาที",
    "eleven_text_to_sound_v2": "$0.12 ต่อนาที",
    "json2video": "~$0.00565 ต่อ credit (1 credit = 1 วิ render, อิงแพลน Hobby $16.95/3000 credits)",
    "cloudinary": "อยู่ใน free tier ปกติ (25 credit/เดือน) - ไม่คิดเงินถ้าไม่เกินโควตา",
}


def log_usage(slug: str, step: str, api: str, item: str, cost_usd: float, detail: str = "") -> None:
    """บันทึก 1 แถวลง cost_log.csv ของคลิปนั้นๆ"""
    log_path = Path("output") / slug / "cost_log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "step", "api", "item", "cost_usd", "cost_thb", "detail"])
        writer.writerow(
            [
                datetime.datetime.now().isoformat(timespec="seconds"),
                step,
                api,
                item,
                f"{cost_usd:.5f}",
                f"{cost_usd * USD_TO_THB:.2f}",
                detail,
            ]
        )


def print_cost_summary(slug: str) -> None:
    """อ่าน cost_log.csv ของคลิปนั้น สรุปยอดตาม step + รวมทั้งหมด แล้วพิมพ์ออกหน้าจอ"""
    log_path = Path("output") / slug / "cost_log.csv"
    if not log_path.exists():
        print("ยังไม่มี cost log สำหรับคลิปนี้")
        return

    with log_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_step: dict[str, float] = {}
    total = 0.0
    for r in rows:
        cost = float(r["cost_usd"])
        by_step[r["step"]] = by_step.get(r["step"], 0.0) + cost
        total += cost

    print("\n===== สรุปค่าใช้จ่ายคลิปนี้ (" + slug + ") =====")
    for step, cost in by_step.items():
        print(f"  {step:22s} ${cost:.4f}   (~{cost * USD_TO_THB:.2f} บาท)")
    print(f"  {'รวมทั้งหมด':22s} ${total:.4f}   (~{total * USD_TO_THB:.2f} บาท)")
    print(f"  บันทึกละเอียดทุกรายการ -> {log_path}")
