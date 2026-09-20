"""
Step 2: "เล่าข่าว + สร้างรูปประกอบ" — สคริปต์+รูปด้วย OpenAI, เสียงพากย์ด้วย ElevenLabs
รองรับหลายภาษาในข่าวเดียวกัน (multi-language, ต่างคลิปแยกกันต่อภาษา)
================================================================
Input  : ข้อความข่าวที่ตรวจสอบแล้ว (มาจาก Step 1 - หาข่าว) + รายการภาษาที่ต้องการ
Output : output/<slug>/<lang>/
           script.json        - สคริปต์ภาษานั้นๆ แบ่ง scene + prompt รูป (จาก gpt-6-astra)
           audio/scene_N.mp3  - เสียงพากย์ภาษานั้นๆ แต่ละฉาก (ElevenLabs)
           images/scene_N.png - รูปประกอบแต่ละฉาก แนวตั้ง 9:16 (gpt-image-2.5-sunburst)
         output/<slug>/cost_log.csv - รวมค่าใช้จ่ายทุกภาษาของข่าวนี้ (แยกดูราย step:lang ได้)

*** นโยบายที่ยืนยันแล้ว (ก.ย. 2569):
    - แต่ละภาษา = สคริปต์เขียนใหม่ทั้งหมดโดย AI (ไม่ใช่แปลตรงจากไทย) โทน/มุมนำเสนอ
      ปรับให้เหมาะกับผู้ชมภาษานั้นได้
    - ข้อความบนภาพ (overlay_text) วาดลงภาพจริงทุกภาษา (ไทย/จีน/ญี่ปุ่น/รัสเซีย ฯลฯ)
      -> ต้องเจนรูปแยกทุกภาษา (ต้นทุนรูปคูณตามจำนวนภาษา) และมีความเสี่ยงสะกดผิดสูงขึ้น
      กับตัวอักษรที่ไม่ใช่ละติน ต้องตรวจทุกภาพด้วยตาก่อนใช้จริง
    - เสียงพากย์: เปลี่ยนจาก OpenAI TTS มาใช้ ElevenLabs แล้ว (เสียงเหมือนคนพูด/นักข่าวจริงกว่า)
      ต้องมี voice_id ที่เหมาะกับแต่ละภาษาแยกกัน (เลือกจาก ElevenLabs Voice Library)

*** อัปเดต (ก.ย. 2569 รอบ 3): เสียงพากย์ "ทุกภาษา" เปลี่ยนมาใช้ Gemini API (native TTS) ทั้งหมด
(เริ่มจากไทยที่ทดสอบแล้ว ElevenLabs Alice ไม่ใช่ภาษาไทยที่ใช้งานได้จริง เลยย้ายทุกภาษามาที่เดียวกัน
เพื่อความสม่ำเสมอ) ElevenLabs ยังใช้อยู่ แต่ "เฉพาะ" Step 3 (ElevenLabs Music + Sound Effects ใน
add_audio_layer.py) ไม่เกี่ยวกับเสียงพากย์คนพูดอีกต่อไป ***

ติดตั้ง : pip install openai requests pydub --break-system-packages  (ต้องมี ffmpeg ในเครื่องด้วย)
ตั้งค่า  : export OPENAI_API_KEY="sk-..."
          export GEMINI_API_KEY="..."          (เสียงพากย์ทุกภาษา - native TTS)
          export ELEVENLABS_API_KEY="..."      (ใช้เฉพาะ Step 3: เพลง+เอฟเฟกต์ ไม่ใช่เสียงพากย์แล้ว)
รัน     : python generate_content.py

หมายเหตุ: โมเดล gpt-6-astra / gpt-image-2.5-sunburst เพิ่งออกปี 2026 (นอก
knowledge cutoff ของผู้เขียนโค้ด) พารามิเตอร์ Responses API บางตัว (เช่น
"text.format") อาจต้องเช็คกับ docs ล่าสุดอีกครั้งก่อนใช้จริงจัง
"""

import base64
import json
import os
import wave
from pathlib import Path

import requests
from openai import OpenAI
from pydub import AudioSegment

from cost_logger import log_usage, print_cost_summary

client = OpenAI()  # อ่าน OPENAI_API_KEY จาก environment variable ให้อัตโนมัติ

SCRIPT_MODEL = "gpt-6-astra"
IMAGE_MODEL = "gpt-image-2.5-sunburst"
IMAGE_SIZE = "1024x1536"  # แนวตั้งใกล้เคียง 9:16 มากที่สุดที่ API รองรับ

ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVEN_TTS_MODEL = "eleven_multilingual_v2"  # รองรับหลายภาษารวมไทย/จีน/ญี่ปุ่น/รัสเซีย

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"  # native TTS, รองรับไทยในรายการทางการ
GEMINI_TTS_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent"
)

OUTPUT_DIR = Path("output")
REFERENCE_IMAGE_PATH = Path("reference_style.png")  # โปสเตอร์ตัวอย่างที่ใช้เป็น "style guide"

# ===== ตั้งค่าต่อภาษา =====
# tts_provider = "gemini" ทุกภาษา (Gemini เลือกภาษาพูดอัตโนมัติจากตัวหนังสือในสคริปต์ ไม่ต้องระบุ
#   language code แยก - เสียง/voice ที่เลือกเป็นแค่ "บุคลิกเสียง" ใช้ข้ามภาษาได้)
# gemini_voice: ชื่อเสียงพรีเมดของ Gemini ตัวเลือกโทนผู้ประกาศข่าว/หนักแน่น: Kore, Charon, Orus,
#   Rasalgethi, Iapetus, Alnilam, Gacrux - ลองเปลี่ยนดูได้เลยถ้าตัวไหนยังไม่เข้ากับเนื้อข่าวหลัง QC
# หมายเหตุ: ElevenLabs (voice_id) เลิกใช้กับเสียงพากย์แล้ว เหลือใช้แค่ Step 3 (เพลง+เอฟเฟกต์ใน
# add_audio_layer.py) โครงสร้าง dict นี้เก็บ tts_provider ไว้เผื่ออนาคตอยากสลับกลับเป็นภาษาใดภาษาหนึ่ง
LANGUAGES = {
    "th": {
        "label": "ไทย",
        "tts_provider": "gemini",
        "gemini_voice": "Kore",
        "voice_id": None,
    },
    "en": {
        "label": "อังกฤษ (English)",
        "tts_provider": "gemini",
        "gemini_voice": "Kore",
        "voice_id": None,
    },
    "zh": {
        "label": "จีนกลาง (Simplified Chinese)",
        "tts_provider": "gemini",
        "gemini_voice": "Charon",
        "voice_id": None,
    },
    "ja": {
        "label": "ญี่ปุ่น",
        "tts_provider": "gemini",
        "gemini_voice": "Orus",
        "voice_id": None,
    },
    "ru": {
        "label": "รัสเซีย",
        "tts_provider": "gemini",
        "gemini_voice": "Rasalgethi",
        "voice_id": None,
    },
}

STYLE_VISION_PROMPT = """ดูภาพอ้างอิงนี้ (เป็นตัวอย่างสไตล์คลิปข่าวที่ต้องการทำตาม) แล้วสรุปเป็นภาษาอังกฤษ
สั้นๆ (ไม่เกิน 60 คำ) เกี่ยวกับ: โทนสี/การจัดแสง, สไตล์การจัดองค์ประกอบภาพ, บรรยากาศโดยรวม,
และลักษณะเสื้อผ้า/ฉาก/สภาพแวดล้อมทั่วไปที่เห็น (เช่น ชนบทไทย, โรงพยาบาลเล็ก, บ้านไม้)

ห้ามอธิบายหน้าตา รูปร่าง หรือระบุตัวตนของบุคคลใดๆ ในภาพโดยเด็ดขาด - บุคคลในภาพต้นฉบับ
ห้ามถูกใช้เป็นต้นแบบใบหน้าของภาพใหม่ ให้พูดถึงแค่โทนภาพ/ฉาก/เสื้อผ้าทั่วไปเท่านั้น
เพื่อเอาไปใช้เป็น style guide ให้ AI สร้างภาพประกอบชุดใหม่ทั้งหมด (คนละภาพ คนละใบหน้า
กับต้นฉบับ 100% แต่โทนภาพและบรรยากาศคล้ายกัน) ใช้ style guide นี้ร่วมกันได้ทุกภาษา
เพราะเป็นเรื่องโทนภาพ/องค์ประกอบ ไม่เกี่ยวกับภาษา"""


def encode_image_to_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def get_style_guide(slug: str, reference_image_path: Path = REFERENCE_IMAGE_PATH) -> str:
    """ใช้ gpt-6-astra (vision) ดูภาพอ้างอิง แล้วสกัดเป็นคำอธิบายโทนภาพ/ฉาก/เสื้อผ้า
    (ไม่ใช่หน้าตาบุคคล) เพื่อให้ทุก scene ในคลิปมีสไตล์ภาพไปทางเดียวกัน เรียกครั้งเดียวต่อข่าว
    แล้วใช้ร่วมกันได้ทุกภาษา (ประหยัด token - โทนภาพไม่ขึ้นกับภาษา)"""
    if not reference_image_path.exists():
        return ""  # ไม่มีภาพอ้างอิง ก็ข้ามไป ใช้ prompt ปกติ
    resp = client.responses.create(
        model=SCRIPT_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": STYLE_VISION_PROMPT},
                    {"type": "input_image", "image_url": encode_image_to_data_url(reference_image_path)},
                ],
            }
        ],
    )
    usage = getattr(resp, "usage", None)
    if usage:
        cost = (usage.input_tokens / 1_000_000) * 10 + (usage.output_tokens / 1_000_000) * 50
        log_usage(slug, "style_guide", "gpt-6-astra", "vision analyze reference image (shared ทุกภาษา)", cost,
                   f"in={usage.input_tokens}tok out={usage.output_tokens}tok")
    return resp.output_text.strip()


def build_system_prompt(style_guide: str, lang_code: str, lang_label: str) -> str:
    """สร้าง system prompt เฉพาะภาษา - ให้ AI เขียนสคริปต์ใหม่ทั้งหมดเป็นภาษานั้น
    (ไม่ใช่แปลจากไทย) แต่ยังคุมโทนภาพให้ตรง STYLE_GUIDE เดียวกันทุกภาษา"""
    non_latin_warning = ""
    if lang_code in ("zh", "ja", "ru"):
        non_latin_warning = (
            f"\n8. ภาษา {lang_label} ใช้ตัวอักษรที่ไม่ใช่ละติน โมเดลสร้างภาพมีความเสี่ยงสะกดผิด/เพี้ยน"
            f" สูงกว่าภาษาอังกฤษมาก ให้ overlay_text สั้นที่สุดเท่าที่จำเป็น (ยิ่งสั้นยิ่งเสี่ยงน้อย)"
            f" และใน image_prompt ต้องระบุชัดเจนว่าให้เขียนด้วยตัวอักษร {lang_label} เท่านั้น"
        )

    return f"""คุณคือนักเขียนสคริปต์ "เล่าข่าวสรุป" สำหรับคลิปสั้น TikTok/Reels/Shorts (แนวตั้ง 9:16)
เขียนสคริปต์นี้เป็นภาษา {lang_label} ทั้งหมด (headline, narration, overlay_text ทุกช่อง)
โดยเขียนขึ้นใหม่ให้เหมาะกับผู้ชมที่พูดภาษา {lang_label} โดยเฉพาะ (ไม่ใช่แปลคำต่อคำจากภาษาอื่น)
ไม่มีตัวคนพูดปรากฏในคลิป (คลิปจะประกอบด้วยรูปที่สร้างขึ้น + เสียงพากย์เท่านั้น)

*** ขั้นแรก: วิเคราะห์ข้อเท็จจริงข่าวที่ให้มา แล้วจัดประเภท (genre) เองว่าเนื้อหาจริงๆ เข้าข่ายไหน
ห้ามสมมติว่าทุกข่าวเป็น "เตือนภัยอันตราย" ตายตัว - ให้เนื้อข่าวเป็นตัวกำหนดโทน/สี/บทสรุปเอง:
  - "เตือนภัย" = มีอันตรายจริงต่อชีวิต/สุขภาพ/ทรัพย์สินที่ผู้ชมต้องระวังตัว (เช่น โรคระบาด, อาชญากรรม,
    ภัยธรรมชาติ, สินค้าอันตราย) -> โทนหนักแน่นห่วงใยแบบพิธีกรข่าวเตือนภัย, ปิดท้ายด้วยคำเตือน/วิธีป้องกันตัว,
    โปสเตอร์สีแดง/เหลือง contrast สูงแบบสัญญาณเตือน
  - "แฟกต์เช็ค" = ตรวจสอบ/หักล้างข่าวลือ, ข้อมูลเท็จ, หรือคำกล่าวอ้างที่ยังไม่ยืนยัน -> โทนที่น่าเชื่อถือ
    เป็นกลาง หนักแน่นแบบนักตรวจสอบข้อเท็จจริง (ไม่ใช่ตื่นตระหนก), ปิดท้ายด้วยสรุปข้อเท็จจริง/คำแนะนำ
    ให้เช็คแหล่งข่าวก่อนเชื่อ-แชร์, โปสเตอร์โทนน้ำเงิน/ขาว หรือเทา-ขาว contrast สูง ดูน่าเชื่อถือ
    (ไม่ใช้สีแดง/เหลืองแบบเตือนภัย เพราะไม่ใช่เรื่องอันตรายจริง)
  - "ข่าวทั่วไป/อัปเดตสถานการณ์" = ข่าวเล่าเหตุการณ์ ไม่มีอันตรายและไม่ใช่การเช็คข่าวลือ -> โทนเล่าข่าว
    กระชับตรงประเด็นแบบสรุปข่าว, ปิดท้ายด้วยสรุปประเด็นสำคัญ/สิ่งที่ต้องติดตามต่อ, โปสเตอร์เลือก "จานสี
    ตามหัวข้อข่าวจริง" ไม่ใช้สีตายตัวซ้ำทุกข่าว - ให้เลือกจานสีที่เข้ากับธีมของข่าวนั้นๆ โดยเฉพาะ เช่น
    กีฬา/แข่งขัน -> โทนสีทีม/สนามแข่ง (เขียวสนามหญ้า, น้ำเงิน-ทอง, ส้ม-ดำแบบกีฬา), บันเทิง/ดารา ->
    ม่วง-ทอง หรือชมพู-ดำสไตล์หรูหรา, เทคโนโลยี/นวัตกรรม -> ฟ้า-ดำหรือฟ้านีออนสไตล์ไซไฟ, เศรษฐกิจ/หุ้น/
    ธุรกิจ -> เขียว-ดำหรือทอง-ดำสไตล์การเงิน, สภาพอากาศ/ภัยธรรมชาติที่ไม่ร้ายแรง -> ส้ม-เทาสไตล์
    พยากรณ์อากาศ, การเมือง/ราชการ -> น้ำเงิน-แดงหรือน้ำเงิน-ขาวสไตล์ทางการ, การศึกษา -> ฟ้า-เหลืองสด
    ให้เลือกจานสีที่ตรงกับหัวข้อข่าวจริงที่สุด (ไม่ต้องยึดตามตัวอย่างนี้เป๊ะๆ ถ้าเนื้อข่าวชี้ไปทางอื่น)
ใส่ genre ที่เลือกไว้ในช่อง "genre" ของ JSON ผลลัพธ์ (ค่าเป็นหนึ่งใน "เตือนภัย" / "แฟกต์เช็ค" / "ข่าวทั่วไป")
สำหรับ genre "ข่าวทั่วไป" ให้ใส่หัวข้อ/ธีมที่ใช้เลือกจานสีไว้ในช่อง "topic" ด้วย (เช่น "กีฬา", "เทคโนโลยี")
ส่วน genre อื่นปล่อย "topic" เป็นค่าว่างได้

กติกาการเขียน:
1. แบ่งสคริปต์เป็น scene ละ 1 ประโยคสั้นๆ (พูดได้ใน 5-8 วินาที/scene) รวม 5-7 scene ต่อคลิป (~30-45 วินาที)
2. Scene แรกต้องเป็น Hook ที่ดึงความสนใจผู้ชมภายใน 3 วินาทีแรก (สไตล์ hook ปรับตาม genre ที่เลือก)
3. Scene สุดท้ายต้องเป็นบทสรุปที่ผู้ชมนำไปใช้ได้จริง โดยรูปแบบขึ้นกับ genre: เตือนภัย -> คำเตือน/วิธี
   ป้องกันตัว, แฟกต์เช็ค -> สรุปข้อเท็จจริง + เตือนให้เช็คก่อนแชร์, ข่าวทั่วไป -> สรุปประเด็น/สิ่งที่ต้องติดตาม
4. ห้ามระบุชื่อเฉพาะของผู้เกี่ยวข้องในข่าว และห้ามอ้างอิงถึงภาพจริงของบุคคลในข่าว
   ให้เล่าเชิงสรุปเหตุการณ์เพื่อการศึกษา/แจ้งข้อมูลสาธารณะเท่านั้น
5. แต่ละ scene ต้องมี overlay_text เป็น "ข้อความสั้นๆ ภาษา {lang_label}" (ไม่เกิน 8 คำ/ตัวอักษรตามความ
   เหมาะสมของภาษานั้น) สไตล์หัวข้อโปสเตอร์ข่าว กระแทกใจ สรุปประเด็นของ scene นั้น สะกดถูกต้อง 100%
6. image_prompt เป็นภาษาอังกฤษ (คำสั่งให้โมเดลสร้างภาพเข้าใจ) บรรยายภาพประกอบที่ "ดัดแปลงจาก
   แหล่งข่าวจริง" ในแง่ฉาก/สถานที่/เสื้อผ้าทั่วไปให้สมจริงและเจาะจงมากขึ้น (ไม่ใช่ภาพนามธรรมทั่วไป)
   แต่ตัวละครทุกคนในภาพต้อง "เป็นคนสมมติที่ AI สร้างขึ้นใหม่ทั้งหมด" หน้าตาต้องไม่เหมือนบุคคลจริง
   ในข่าวแม้แต่น้อย (เปลี่ยนหน้าตา/รูปร่างให้ต่างไปสิ้นเชิง) อาจให้เสื้อผ้าและบรรยากาศฉากคล้ายของจริงได้
   และต้องระบุชัดเจนในทุก image_prompt ให้ AI วาดข้อความ overlay_text ของ scene นั้นลงในภาพโดยตรง
   แบบตัวหนา สไตล์โปสเตอร์ที่ "ตรงกับ genre (และ topic ถ้าเป็นข่าวทั่วไป) ที่เลือกไว้ข้างต้น"
   (เตือนภัย = แดง/เหลือง contrast สูง, แฟกต์เช็ค = น้ำเงิน/ขาวหรือเทา-ขาว contrast สูง, ข่าวทั่วไป =
   จานสีตาม topic ที่เลือก เช่น กีฬา->เขียวสนาม/น้ำเงิน-ทอง, บันเทิง->ม่วง-ทอง, เทคโนโลยี->ฟ้า-ดำ)
   อ่านง่าย สะกดตามที่ให้เป๊ะๆ ห้ามเพี้ยน เช่น: "...overlay the {lang_label} text '<overlay_text>'
   (written in {lang_label} script/characters) as bold high-contrast poster-style typography in a
   color scheme matching the <genre/topic> tone, spelled EXACTLY as given, clearly legible,
   positioned at top or bottom third..."
7. ทุก image_prompt ต้องคุมโทนภาพ/สไตล์การถ่าย/แสง ให้ตรงกับ STYLE_GUIDE นี้เหมือนกันทุก scene
   เพื่อให้ภาพทั้งคลิปดูเป็นชุดเดียวกัน (ใช้ style guide เดียวกับเวอร์ชันภาษาอื่นของข่าวนี้ เพื่อให้
   แบรนด์คลิปดูสอดคล้องกันข้ามภาษา) - ปรับสีโปสเตอร์ตาม genre ได้ตามข้อ 6 แต่โทนภาพ/แสง/บรรยากาศ
   โดยรวมยังคงตาม STYLE_GUIDE เดิม:
   STYLE_GUIDE: {style_guide}{non_latin_warning}

ตอบกลับเป็น JSON ล้วนตาม schema นี้เท่านั้น ห้ามมีข้อความอื่นนอก JSON (ค่าทุกช่องเป็นภาษา {lang_label}
ยกเว้น genre และ image_prompt ที่เป็นภาษาอังกฤษ):
{{
  "genre": "เตือนภัย | แฟกต์เช็ค | ข่าวทั่วไป (เลือกตามเนื้อข่าวจริง ห้ามเลือกมั่ว)",
  "topic": "หัวข้อ/ธีมของข่าว เช่น กีฬา, เทคโนโลยี, บันเทิง, เศรษฐกิจ (ใส่เฉพาะตอน genre เป็น 'ข่าวทั่วไป' ใช้เลือกจานสีโปสเตอร์ - genre อื่นปล่อยว่างได้)",
  "headline": "พาดหัวคลิปสั้น กระชับ ดึงดูด ไม่เกิน 12 คำ",
  "scenes": [
    {{"narration": "บทพากย์ของฉากนี้ภาษา {lang_label}", "overlay_text": "ข้อความสั้นๆ ภาษา {lang_label} บนภาพ", "image_prompt": "English description for image generation, must include exact instruction to render the {lang_label} overlay_text as bold poster typography in the genre/topic-appropriate color scheme"}}
  ]
}}
"""


def generate_script(slug: str, news_facts: str, lang_code: str, style_guide: str = "") -> dict:
    """เรียก gpt-6-astra เพื่อเขียนสคริปต์เล่าข่าวเป็นภาษา lang_code ใหม่ทั้งหมด (ไม่ใช่แปล)
    โดยฝัง style_guide (สกัดจากภาพอ้างอิงจริง, ใช้ร่วมกันทุกภาษา) เข้าไปคุมโทนภาพให้ไปทางเดียวกัน"""
    lang_label = LANGUAGES[lang_code]["label"]
    system_prompt = build_system_prompt(
        style_guide or "cinematic photorealistic editorial news photography, dramatic natural lighting",
        lang_code,
        lang_label,
    )
    resp = client.responses.create(
        model=SCRIPT_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"ข้อเท็จจริงข่าว (ตรวจสอบแล้ว):\n{news_facts}"},
        ],
        text={"format": {"type": "json_object"}},
    )
    usage = getattr(resp, "usage", None)
    if usage:
        cost = (usage.input_tokens / 1_000_000) * 10 + (usage.output_tokens / 1_000_000) * 50
        log_usage(slug, f"script:{lang_code}", "gpt-6-astra", f"generate script JSON ({lang_label})", cost,
                   f"in={usage.input_tokens}tok out={usage.output_tokens}tok")
    return json.loads(resp.output_text)


def generate_tts_elevenlabs(slug: str, text: str, out_path: Path, voice_id: str, lang_code: str) -> None:
    """เรียก ElevenLabs สร้างเสียงพากย์ของ 1 scene แล้วเซฟเป็น mp3"""
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
        params={"output_format": "mp3_44100_128"},
        json={
            "text": text,
            "model_id": ELEVEN_TTS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3},
        },
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)

    cost = (len(text) / 1000) * 0.10  # eleven_multilingual_v2 = $0.10 / 1,000 ตัวอักษร
    log_usage(slug, f"tts:{lang_code}", ELEVEN_TTS_MODEL, out_path.name, cost, f"{len(text)} ตัวอักษร")


def generate_tts_gemini(slug: str, text: str, out_path: Path, voice_name: str, lang_code: str) -> None:
    """เรียก Gemini API (native TTS) สร้างเสียงพากย์ของ 1 scene - ใช้แทน ElevenLabs สำหรับภาษาที่เสียง
    ไม่เข้ากับภาษา (เริ่มจากไทย) API คืนค่าเป็น raw PCM (24kHz/16-bit/mono) ต้อง wrap เป็น WAV เอง
    ก่อนแปลงเป็น mp3 ด้วย pydub ให้ format ตรงกับไฟล์อื่นในระบบ (Step 3/4 ใช้ .mp3 ต่อ)"""
    resp = requests.post(
        GEMINI_TTS_ENDPOINT,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}},
            },
        },
    )
    resp.raise_for_status()
    data = resp.json()
    b64_audio = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    pcm_bytes = base64.b64decode(b64_audio)

    wav_path = out_path.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    AudioSegment.from_wav(wav_path).export(out_path, format="mp3")
    wav_path.unlink(missing_ok=True)

    usage = data.get("usageMetadata", {})
    input_tokens = usage.get("promptTokenCount")
    output_tokens = usage.get("candidatesTokenCount")
    if input_tokens is not None and output_tokens is not None:
        cost = (input_tokens / 1_000_000) * 1.0 + (output_tokens / 1_000_000) * 20.0
        detail = f"in={input_tokens}tok out={output_tokens}tok(audio)"
    else:
        duration_sec = len(pcm_bytes) / (24000 * 2)  # 16-bit mono @ 24kHz
        cost = duration_sec * 25 * 20 / 1_000_000  # ~25 audio token/วิ, $20/1M output token
        detail = f"~{duration_sec:.1f}s เสียง (API ไม่คืน token count - ประมาณจากความยาว)"
    log_usage(slug, f"tts:{lang_code}", GEMINI_TTS_MODEL, out_path.name, cost, detail)


def generate_tts(slug: str, text: str, out_path: Path, lang_code: str) -> None:
    """สลับผู้ให้บริการ TTS อัตโนมัติตาม tts_provider ที่ตั้งไว้ต่อภาษาใน LANGUAGES"""
    lang = LANGUAGES[lang_code]
    if lang["tts_provider"] == "gemini":
        generate_tts_gemini(slug, text, out_path, lang["gemini_voice"], lang_code)
    else:
        generate_tts_elevenlabs(slug, text, out_path, lang["voice_id"], lang_code)


def generate_image(slug: str, prompt: str, out_path: Path, lang_code: str) -> None:
    """เรียก gpt-image-2.5-sunburst สร้างรูปประกอบ 1 scene แนวตั้ง (แยกเจนทุกภาษา
    เพราะข้อความบนภาพเป็นคนละภาษา)"""
    result = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=IMAGE_SIZE,
        quality="high",
    )
    image_bytes = base64.b64decode(result.data[0].b64_json)
    out_path.write_bytes(image_bytes)

    usage = getattr(result, "usage", None)
    if usage:
        cost = (usage.input_tokens / 1_000_000) * 5 + (usage.output_tokens / 1_000_000) * 30
        log_usage(slug, f"image:{lang_code}", IMAGE_MODEL, out_path.name, cost,
                   f"in={usage.input_tokens}tok out={usage.output_tokens}tok")
    else:
        log_usage(slug, f"image:{lang_code}", IMAGE_MODEL, out_path.name, 0.0,
                   "API ไม่คืนค่า usage - เช็คราคาจริงที่ platform.openai.com/usage")


def _job_dir(slug: str) -> Path:
    return OUTPUT_DIR / slug


def _news_facts_path(slug: str) -> Path:
    return _job_dir(slug) / "news_facts.txt"


def _style_guide_path(slug: str) -> Path:
    return _job_dir(slug) / "style_guide.txt"


def save_job_news_facts(slug: str, news_facts: str) -> None:
    """เก็บข้อเท็จจริงข่าวไว้ระดับ job (ไม่ใช่ต่อภาษา) ใช้ตอนกลับมาเพิ่มภาษาทีหลังโดยไม่ต้องพิมพ์ซ้ำ"""
    _job_dir(slug).mkdir(parents=True, exist_ok=True)
    _news_facts_path(slug).write_text(news_facts, encoding="utf-8")


def load_job_news_facts(slug: str) -> str:
    p = _news_facts_path(slug)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def get_or_create_style_guide(slug: str) -> str:
    """ใช้ style guide ที่เคยเจนไว้แล้วของข่าวนี้ถ้ามี (เก็บเป็นไฟล์ระดับ job) กันเรียก gpt-6-astra
    vision ซ้ำทุกครั้งที่กลับมาเพิ่มภาษา - ประหยัดเงินและคุมสไตล์ภาพให้เหมือนเดิมทุกภาษา/ทุกรอบ"""
    p = _style_guide_path(slug)
    if p.exists():
        return p.read_text(encoding="utf-8")
    style_guide = get_style_guide(slug)
    if style_guide:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(style_guide, encoding="utf-8")
    return style_guide


def list_jobs() -> list[dict]:
    """สแกน output/ หาข่าวที่เคยทำไว้ทั้งหมด คืน slug, headline (preview), ภาษาที่ทำไปแล้ว,
    เวลาแก้ไขล่าสุด (ใหม่สุดก่อน) ใช้แสดงในหน้า 'ข่าวเดิม' ของเว็บแอป ให้กลับมาเพิ่มภาษาทีหลังได้"""
    jobs = []
    if not OUTPUT_DIR.exists():
        return jobs
    for job_dir in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not job_dir.is_dir():
            continue
        slug = job_dir.name
        news_facts = load_job_news_facts(slug)
        done_langs = [
            lang_code for lang_code in LANGUAGES
            if (job_dir / lang_code / "script.json").exists()
        ]
        if not done_langs and not news_facts:
            continue  # ไม่ใช่ job ของระบบนี้ (เช่นโฟลเดอร์เก่าก่อนอัปเดต multi-language) ข้ามไป
        headline = ""
        for lang_code in done_langs:
            try:
                script = json.loads((job_dir / lang_code / "script.json").read_text(encoding="utf-8"))
                headline = script.get("headline", "")
                break
            except Exception:
                continue
        jobs.append({
            "slug": slug,
            "news_facts": news_facts,
            "headline": headline,
            "done_langs": done_langs,
            "mtime": job_dir.stat().st_mtime,
        })
    return jobs


def run_one_language(news_facts: str, slug: str, lang_code: str, style_guide: str) -> Path:
    """ผลิตคลิป 1 ภาษา (สคริปต์ + เสียง + รูป ครบชุด) ลง output/<slug>/<lang_code>/"""
    lang = LANGUAGES[lang_code]
    if lang["tts_provider"] == "elevenlabs" and not lang["voice_id"]:
        raise ValueError(
            f"ยังไม่ได้ตั้ง voice_id สำหรับภาษา {lang['label']} ({lang_code}) - "
            f"ไปเลือกเสียงจาก ElevenLabs Voice Library แล้วตั้ง env var ELEVEN_VOICE_ID_{lang_code.upper()} ก่อน"
        )
    if lang["tts_provider"] == "gemini" and not GEMINI_API_KEY:
        raise ValueError(f"ยังไม่ได้ตั้ง GEMINI_API_KEY - export ก่อนรันภาษา {lang['label']}")

    job_dir = OUTPUT_DIR / slug / lang_code
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)
    (job_dir / "images").mkdir(parents=True, exist_ok=True)

    print(f"\n=== ภาษา: {lang['label']} ({lang_code}) -> {job_dir}/ ===")
    print(f"[1/3] กำลังสร้างสคริปต์ด้วย {SCRIPT_MODEL} ...")
    script = generate_script(slug, news_facts, lang_code, style_guide)
    (job_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  หัวข้อ: {script['headline']} | {len(script['scenes'])} scenes")

    for i, scene in enumerate(script["scenes"], start=1):
        tts_label = GEMINI_TTS_MODEL if lang["tts_provider"] == "gemini" else ELEVEN_TTS_MODEL
        print(f"[2/3] Scene {i}: สร้างเสียงพากย์ ({tts_label}) ...")
        generate_tts(slug, scene["narration"], job_dir / "audio" / f"scene_{i}.mp3", lang_code)

        print(f"[3/3] Scene {i}: สร้างรูปประกอบ ({IMAGE_MODEL}) ...")
        generate_image(slug, scene["image_prompt"], job_dir / "images" / f"scene_{i}.png", lang_code)

    print(f"เสร็จภาษา {lang['label']} -> {job_dir}/")
    return job_dir


def run(news_facts: str, slug: str, languages: list[str] = ("th",)) -> dict[str, Path]:
    """ผลิตข่าวเดียวกัน หลายภาษาพร้อมกัน (ต่างคลิปแยกกันต่อภาษา)
    style_guide เจนครั้งเดียวใช้ร่วมกันทุกภาษา (ประหยัด token, ภาพดูเป็นแบรนด์เดียวกัน)
    เก็บ news_facts + style_guide ไว้ระดับ job (ไฟล์ .txt ใน output/<slug>/) ให้กลับมา
    เพิ่มภาษาทีหลังได้โดยไม่ต้องพิมพ์ข่าวซ้ำ และไม่ต้องเรียก vision model ซ้ำ (ประหยัดเงิน)"""
    save_job_news_facts(slug, news_facts)

    print("[0] วิเคราะห์ภาพอ้างอิงเพื่อทำ style guide (ใช้ร่วมกันทุกภาษา + ทุกรอบที่กลับมาเพิ่มภาษา) ...")
    style_guide = get_or_create_style_guide(slug)
    if style_guide:
        print(f"  style_guide: {style_guide[:80]}...")

    job_dirs = {}
    for lang_code in languages:
        job_dirs[lang_code] = run_one_language(news_facts, slug, lang_code, style_guide)

    print(f"\nเสร็จทั้งหมด {len(languages)} ภาษา -> {OUTPUT_DIR / slug}/")
    print_cost_summary(slug)
    return job_dirs


if __name__ == "__main__":
    # ตัวอย่างข้อมูลข่าว (ตรวจสอบแล้วจาก Step 1 - หาข่าว)
    example_news = """
    หญิงวัย 43 ปี ชาว ต.ปลาปาก อ.ปลาปาก จ.นครพนม เสียชีวิตวันที่ 9 ก.ย. 2569
    หลังถูกลูกสุนัขวัย 1 เดือนกัดที่ขาเมื่อ 3 เดือนก่อน แต่ไม่ได้ไปพบแพทย์
    ต่อมามีอาการอ่อนแรงและปวดขา เข้ารักษาตัวที่ รพ.ปลาปาก เพียง 2 วันก่อนเสียชีวิต
    ผลตรวจยืนยันเป็นโรคพิษสุนัขบ้า ทางการประกาศตำบลปลาปากเป็นเขตโรคระบาด
    และเร่งฉีดวัคซีนป้องกันให้สุนัข-แมวในพื้นที่ราว 1,000 ตัว ครอบคลุม 100%
    """
    run(example_news, slug="20260920-rabies-plapak", languages=["th", "en", "zh"])
