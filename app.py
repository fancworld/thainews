"""
Web UI (Phase 1 - MVP): เว็บฟอร์มเดียว รหัสผ่านรวม สำหรับรัน pipeline 4 ขั้นตอนเดิม
================================================================
ไม่ได้เขียน logic การเจนคอนเทนต์ใหม่ - แค่ห่อ (wrap) 4 สคริปต์เดิมที่ทดสอบผ่านแล้ว:
  generate_content.py  (Step 2: สคริปต์+เสียง+รูป, แยกทุกภาษาที่เลือก)
  add_audio_layer.py   (Step 3: เพลง+เอฟเฟกต์ ElevenLabs)
  assemble_video.py    (Step 4: รวมคลิป JSON2Video)
  cost_logger.py        (สรุปค่าใช้จ่าย)

ออกแบบเป็น step-by-step เหมือนที่ทดสอบผ่าน CLI มาตลอด: เจนสคริปต์+รูปก่อน ให้ดู/เช็ค
สะกดคำ (โดยเฉพาะภาษาที่ไม่ใช่ไทย/อังกฤษ) ก่อนค่อยกดขั้นถัดไป กันเสียเงินเจนเสียง/รวมคลิป
ทั้งที่รูปยังผิดอยู่

*** อัปเดต: เพิ่มโหมด "ข่าวเดิม (เพิ่มภาษา)" ***
งานเก่าแต่ละงาน (slug) เก็บ news_facts.txt + style_guide.txt ไว้ที่ output/<slug>/ แล้ว
(ทำใน generate_content.py) กลับมาเลือกเพิ่มภาษาใหม่ทีหลังได้โดยไม่ต้องพิมพ์ข่าวซ้ำ และไม่ต้อง
เจน style guide ใหม่ (ประหยัดเงิน + ภาพยังคุมโทนเดียวกับภาษาที่ทำไปแล้ว)

รันทดสอบในเครื่องก่อน deploy จริง:
  pip install -r requirements.txt --break-system-packages
  streamlit run app.py

Deploy ขึ้น Render: ดู Dockerfile + render.yaml ในโฟลเดอร์เดียวกัน
ต้องตั้ง environment variables ในหน้า Render Dashboard (ไม่ใส่ในโค้ด):
  OPENAI_API_KEY, GEMINI_API_KEY, ELEVENLABS_API_KEY, CLOUDINARY_URL, JSON2VIDEO_API_KEY, APP_PASSWORD
"""

import datetime
import json as _json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

import add_audio_layer
import assemble_video
import generate_content
from cost_logger import USD_TO_THB

st.set_page_config(page_title="เล่าข่าว AI Pipeline", page_icon="📰", layout="wide")

APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")


# ===== รหัสผ่านรวม (Phase 1 - ยังไม่มีระบบบัญชีแยกลูกค้า) =====
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("📰 เล่าข่าว AI Pipeline")
    pw = st.text_input("รหัสผ่าน", type="password")
    if st.button("เข้าใช้งาน"):
        if pw == APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("รหัสผ่านไม่ถูกต้อง")
    return False


if not check_password():
    st.stop()


# ===== ตัวช่วย =====
def make_slug(headline_hint: str = "") -> str:
    """สร้าง slug จากวันเวลา + คำใบ้หัวข้อ (กันชื่อไทยที่ทำ URL/foldername ไม่ได้ตรงๆ)"""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    hint = re.sub(r"[^a-zA-Z0-9]+", "-", headline_hint.strip()).strip("-").lower()
    hint = hint[:30] if hint else "news"
    return f"{ts}-{hint}"


def load_cost_table(slug: str) -> pd.DataFrame | None:
    log_path = Path("output") / slug / "cost_log.csv"
    if not log_path.exists():
        return None
    return pd.read_csv(log_path)


def job_dirs_for_done_langs(slug: str, done_langs: list[str]) -> dict[str, str]:
    """คืน path ของภาษาที่ทำไปแล้วของ job นี้ (ใช้ตอนกลับมาเปิดงานเดิม เพื่อให้ QC/Step2/Step3
    เห็นภาษาที่เคยทำไว้ครบ ไม่ใช่แค่ภาษาที่เพิ่งเจนใหม่รอบนี้)"""
    return {lc: str(generate_content.OUTPUT_DIR / slug / lc) for lc in done_langs}


LANG_CHOICES = {
    "th": "ไทย",
    "en": "อังกฤษ (English)",
    "zh": "จีนกลาง (Chinese)",
    "ja": "ญี่ปุ่น (Japanese)",
    "ru": "รัสเซีย (Russian)",
}

if "slug" not in st.session_state:
    st.session_state["slug"] = None
if "job_dirs" not in st.session_state:
    st.session_state["job_dirs"] = {}
if "news_facts_current" not in st.session_state:
    st.session_state["news_facts_current"] = ""

st.title("📰 เล่าข่าว AI Pipeline")
st.caption("หาข่าว (ทำเองนอกระบบ) → สคริปต์+เสียง+รูป → เสียงประกอบ → รวมคลิป")

# ===== เลือกโหมด: ข่าวใหม่ / ข่าวเดิม (เพิ่มภาษา) =====
if st.session_state["slug"] is not None:
    st.info(
        f"กำลังทำงาน: `{st.session_state['slug']}` "
        f"(ภาษาที่มีแล้ว: {', '.join(LANG_CHOICES.get(c, c) for c in st.session_state['job_dirs']) or '-'})"
    )
    if st.button("🔄 เริ่มงานใหม่ / เลือกข่าวอื่น"):
        st.session_state["slug"] = None
        st.session_state["job_dirs"] = {}
        st.session_state["news_facts_current"] = ""
        st.rerun()

mode = st.radio(
    "เลือกงาน",
    ["🆕 ข่าวใหม่", "📂 ข่าวเดิม (เพิ่มภาษา)"],
    horizontal=True,
    disabled=st.session_state["slug"] is not None,
)

# ===== โหมด: ข่าวใหม่ =====
if mode == "🆕 ข่าวใหม่" and st.session_state["slug"] is None:
    st.header("ขั้นตอน 1 — สคริปต์ + เสียงพากย์ + รูป (Step 2 เดิม)")

    news_facts = st.text_area(
        "ข้อเท็จจริงข่าว (ตรวจสอบแล้วเอง ก่อนวาง)",
        height=150,
        placeholder="เช่น หญิงวัย 43 ปี ชาว ต.ปลาปาก ... เสียชีวิตด้วยโรคพิษสุนัขบ้า ...",
    )
    headline_hint = st.text_input("คำใบ้ชื่อไฟล์งาน (ภาษาอังกฤษสั้นๆ เช่น rabies-plapak)", value="")

    selected_langs = st.multiselect(
        "เลือกภาษาที่จะผลิต (แต่ละภาษา = เจนสคริปต์+เสียง+รูปแยกชุด ต้นทุนคูณตามจำนวนที่เลือก - "
        "เพิ่มภาษาอื่นทีหลังได้ผ่านโหมด 'ข่าวเดิม (เพิ่มภาษา)')",
        options=list(LANG_CHOICES.keys()),
        format_func=lambda c: LANG_CHOICES[c],
        default=["th"],
    )

    missing_elevenlabs = [
        c for c in selected_langs
        if generate_content.LANGUAGES[c]["tts_provider"] == "elevenlabs" and not generate_content.LANGUAGES[c]["voice_id"]
    ]
    missing_gemini = [
        c for c in selected_langs
        if generate_content.LANGUAGES[c]["tts_provider"] == "gemini" and not generate_content.GEMINI_API_KEY
    ]
    if missing_elevenlabs:
        st.warning(
            "ยังไม่ได้ตั้ง voice_id (ElevenLabs) สำหรับ: "
            + ", ".join(LANG_CHOICES[c] for c in missing_elevenlabs)
            + " — ไปเลือกเสียงจาก ElevenLabs Voice Library แล้วตั้ง environment variable "
            + " / ".join(f"ELEVEN_VOICE_ID_{c.upper()}" for c in missing_elevenlabs)
            + " ก่อน (จะรันภาษานั้นไม่ได้จนกว่าจะตั้งค่า)"
        )
    if missing_gemini:
        st.warning(
            "ยังไม่ได้ตั้ง GEMINI_API_KEY (ใช้เจนเสียง: " + ", ".join(LANG_CHOICES[c] for c in missing_gemini) + ")"
        )

    if st.button("🚀 เริ่มเจนสคริปต์+เสียง+รูป", disabled=not news_facts or not selected_langs):
        slug = make_slug(headline_hint)
        with st.spinner(f"กำลังผลิต {len(selected_langs)} ภาษา ({slug}) ... อาจใช้เวลาหลายนาที"):
            try:
                job_dirs = generate_content.run(news_facts, slug, languages=selected_langs)
                st.session_state["slug"] = slug
                st.session_state["job_dirs"] = {k: str(v) for k, v in job_dirs.items()}
                st.session_state["news_facts_current"] = news_facts
                st.success("เจนสคริปต์+เสียง+รูปเสร็จแล้ว เลื่อนลงไปเช็คผล QC ก่อนไปขั้นตอน 2")
                st.rerun()
            except Exception as e:
                st.error(f"ล้มเหลว: {e}")

# ===== โหมด: ข่าวเดิม (เพิ่มภาษา) =====
if mode == "📂 ข่าวเดิม (เพิ่มภาษา)" and st.session_state["slug"] is None:
    st.header("เลือกข่าวเดิมที่จะเพิ่มภาษา")
    jobs = generate_content.list_jobs()
    if not jobs:
        st.info("ยังไม่มีข่าวเดิมในระบบ (ยังไม่เคยเจนงานไหนสำเร็จ) - ไปที่โหมด '🆕 ข่าวใหม่' ก่อน")
    else:
        job_options = {
            f"{j['slug']} — {j['headline'] or '(ยังไม่มีหัวข้อ)'} "
            f"[{', '.join(LANG_CHOICES.get(c, c) for c in j['done_langs']) or '-'}]": j
            for j in jobs
        }
        picked_label = st.selectbox("งานเดิม (ใหม่สุดอยู่บนสุด)", options=list(job_options.keys()))
        picked_job = job_options[picked_label]

        st.text_area("ข้อเท็จจริงข่าวของงานนี้ (ใช้ซ้ำ ไม่ต้องพิมพ์ใหม่)", value=picked_job["news_facts"],
                      height=100, disabled=True)
        st.caption(
            "ภาษาที่ทำไปแล้ว: "
            + (", ".join(LANG_CHOICES.get(c, c) for c in picked_job["done_langs"]) or "-")
        )

        remaining_langs = [c for c in LANG_CHOICES if c not in picked_job["done_langs"]]
        if not remaining_langs:
            st.success("ทำครบทุกภาษาที่รองรับแล้วสำหรับข่าวนี้")
            new_langs = []
        else:
            new_langs = st.multiselect(
                "เลือกภาษาที่จะเพิ่ม (style guide เดิมจะถูกใช้ซ้ำ ทำให้ภาพยังคุมโทนเดียวกับภาษาที่ทำไปแล้ว)",
                options=remaining_langs,
                format_func=lambda c: LANG_CHOICES[c],
            )

        missing_elevenlabs = [
            c for c in new_langs
            if generate_content.LANGUAGES[c]["tts_provider"] == "elevenlabs" and not generate_content.LANGUAGES[c]["voice_id"]
        ]
        missing_gemini = [
            c for c in new_langs
            if generate_content.LANGUAGES[c]["tts_provider"] == "gemini" and not generate_content.GEMINI_API_KEY
        ]
        if missing_elevenlabs:
            st.warning(
                "ยังไม่ได้ตั้ง voice_id (ElevenLabs) สำหรับ: "
                + ", ".join(LANG_CHOICES[c] for c in missing_elevenlabs)
            )
        if missing_gemini:
            st.warning(
                "ยังไม่ได้ตั้ง GEMINI_API_KEY (ใช้เจนเสียง: "
                + ", ".join(LANG_CHOICES[c] for c in missing_gemini) + ")"
            )

        col_open, col_add = st.columns(2)
        if col_open.button("📂 เปิดงานนี้ (ดูของเดิมก่อน ไม่เพิ่มภาษา)"):
            st.session_state["slug"] = picked_job["slug"]
            st.session_state["job_dirs"] = job_dirs_for_done_langs(picked_job["slug"], picked_job["done_langs"])
            st.session_state["news_facts_current"] = picked_job["news_facts"]
            st.rerun()

        if col_add.button("➕ เพิ่มภาษาที่เลือก", disabled=not new_langs):
            slug = picked_job["slug"]
            with st.spinner(f"กำลังเพิ่ม {len(new_langs)} ภาษา ({slug}) ... อาจใช้เวลาหลายนาที"):
                try:
                    new_job_dirs = generate_content.run(picked_job["news_facts"], slug, languages=new_langs)
                    merged = job_dirs_for_done_langs(slug, picked_job["done_langs"])
                    merged.update({k: str(v) for k, v in new_job_dirs.items()})
                    st.session_state["slug"] = slug
                    st.session_state["job_dirs"] = merged
                    st.session_state["news_facts_current"] = picked_job["news_facts"]
                    st.success("เพิ่มภาษาเสร็จแล้ว เลื่อนลงไปเช็คผล QC")
                    st.rerun()
                except Exception as e:
                    st.error(f"ล้มเหลว: {e}")

# ===== แสดงผล QC: สคริปต์ + รูป ต่อภาษา =====
if st.session_state["slug"]:
    slug = st.session_state["slug"]
    st.divider()
    st.subheader(f"ผลลัพธ์งาน: `{slug}`")

    for lang_code, job_dir_str in st.session_state["job_dirs"].items():
        job_dir = Path(job_dir_str)
        script_path = job_dir / "script.json"
        if not script_path.exists():
            continue

        script = _json.loads(script_path.read_text(encoding="utf-8"))

        with st.expander(f"🔍 QC ภาษา: {LANG_CHOICES.get(lang_code, lang_code)} — {script['headline']}", expanded=True):
            st.caption("เช็คการสะกดคำในรูปให้ครบทุก scene ก่อนไปขั้นตอนถัดไป (โดยเฉพาะภาษาที่ไม่ใช่ละติน)")
            cols = st.columns(len(script["scenes"]) or 1)
            for i, scene in enumerate(script["scenes"], start=1):
                img_path = job_dir / "images" / f"scene_{i}.png"
                with cols[i - 1]:
                    if img_path.exists():
                        st.image(str(img_path), caption=f"Scene {i}")
                    st.caption(scene.get("overlay_text", ""))
                    audio_path = job_dir / "audio" / f"scene_{i}.mp3"
                    if audio_path.exists():
                        st.audio(str(audio_path))

    # ===== ขั้นตอน 2: เสียงประกอบ =====
    st.divider()
    st.header("ขั้นตอน 2 — เพลง + เอฟเฟกต์ประกอบ (Step 3 เดิม)")
    langs_ready = list(st.session_state["job_dirs"].keys())
    langs_for_audio = st.multiselect(
        "เลือกภาษาที่ QC ผ่านแล้ว จะทำเสียงประกอบต่อ",
        options=langs_ready,
        format_func=lambda c: LANG_CHOICES.get(c, c),
        default=langs_ready,
        key="audio_langs",
    )
    if st.button("🎵 เพิ่มเสียงประกอบ", disabled=not langs_for_audio):
        for lang_code in langs_for_audio:
            job_dir_str = st.session_state["job_dirs"][lang_code]
            with st.spinner(f"กำลังทำเสียงประกอบ ({LANG_CHOICES.get(lang_code, lang_code)}) ..."):
                try:
                    add_audio_layer.run(job_dir_str)
                    st.success(f"เสียงประกอบ {LANG_CHOICES.get(lang_code, lang_code)} เสร็จแล้ว")
                except Exception as e:
                    st.error(f"{LANG_CHOICES.get(lang_code, lang_code)} ล้มเหลว: {e}")

    # ===== ขั้นตอน 3: รวมคลิป =====
    st.divider()
    st.header("ขั้นตอน 3 — รวมคลิปสุดท้าย (Step 4 เดิม, JSON2Video)")
    langs_for_render = st.multiselect(
        "เลือกภาษาที่พร้อมรวมคลิป (ต้องผ่านขั้นตอน 2 มาก่อน)",
        options=langs_ready,
        format_func=lambda c: LANG_CHOICES.get(c, c),
        default=langs_ready,
        key="render_langs",
    )
    if st.button("🎬 รวมคลิป", disabled=not langs_for_render):
        for lang_code in langs_for_render:
            job_dir_str = st.session_state["job_dirs"][lang_code]
            with st.spinner(f"กำลัง render คลิป ({LANG_CHOICES.get(lang_code, lang_code)}) ... รอ JSON2Video ~1-3 นาที"):
                try:
                    out_path = assemble_video.run(job_dir_str)
                    st.success(f"คลิป {LANG_CHOICES.get(lang_code, lang_code)} เสร็จแล้ว")
                    st.video(str(out_path))
                    with open(out_path, "rb") as f:
                        st.download_button(
                            f"⬇️ ดาวน์โหลด {LANG_CHOICES.get(lang_code, lang_code)}",
                            f,
                            file_name=out_path.name,
                            key=f"dl_{lang_code}",
                        )
                except Exception as e:
                    st.error(f"{LANG_CHOICES.get(lang_code, lang_code)} ล้มเหลว: {e}")

    # ===== สรุปค่าใช้จ่าย =====
    st.divider()
    st.header("💰 สรุปค่าใช้จ่ายงานนี้")
    df = load_cost_table(slug)
    if df is not None and not df.empty:
        by_step = df.groupby("step")["cost_usd"].sum().sort_values(ascending=False)
        total_usd = df["cost_usd"].sum()
        c1, c2 = st.columns(2)
        c1.metric("รวมทั้งหมด (USD)", f"${total_usd:,.4f}")
        c2.metric("รวมทั้งหมด (THB)", f"฿{total_usd * USD_TO_THB:,.2f}")
        st.bar_chart(by_step)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("ยังไม่มีข้อมูลค่าใช้จ่ายสำหรับงานนี้")
