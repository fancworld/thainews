"""
Step 3: ใส่เสียงประกอบ (เพลง + เอฟเฟกต์) ด้วย ElevenLabs
================================================================
Input  : output/<slug>/  (ผลลัพธ์จาก Step 2 - มี script.json + audio/scene_N.mp3)
Output : output/<slug>/audio_bg/
           music.mp3       - เพลงพื้นหลังยาวเท่าความยาวคลิป (ElevenLabs Music)
           sfx_hook.mp3    - เอฟเฟกต์เสียงตอนเปิด (ดึงความสนใจ)
           sfx_warning.mp3 - เอฟเฟกต์เสียงตอนเข้าเนื้อหาคำเตือน

ติดตั้ง : pip install requests pydub --break-system-packages
          (pydub ต้องมี ffmpeg ติดตั้งในเครื่องด้วย)
ตั้งค่า  : export ELEVENLABS_API_KEY="..."
รัน     : python add_audio_layer.py output/20260920-rabies-plapak

อ้างอิง API (เช็คกับ docs ล่าสุดก่อนใช้จริงจัง เผื่อมีอัปเดต):
  Music        : POST https://api.elevenlabs.io/v1/music   (model_id="music_v2")
  Sound Effects: POST https://api.elevenlabs.io/v1/sound-generation (model_id="eleven_text_to_sound_v2")
"""

import json
import os
import sys
from pathlib import Path

import requests
from pydub import AudioSegment

from cost_logger import log_usage, print_cost_summary

MUSIC_ENDPOINT = "https://api.elevenlabs.io/v1/music"
SFX_ENDPOINT = "https://api.elevenlabs.io/v1/sound-generation"


def _headers() -> dict:
    """อ่าน ELEVENLABS_API_KEY แบบ lazy (ตอนเรียกจริง ไม่ใช่ตอน import) กัน error ทำเว็บแอปพังทั้งหน้า
    ตั้งแต่โหลดครั้งแรก ทั้งที่ผู้ใช้อาจแค่อยากทดสอบ Step 2 ที่ยังไม่เกี่ยวกับ ElevenLabs เลย"""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้ง ELEVENLABS_API_KEY - export/setx ก่อนใช้ Step 3 (เพลง+เอฟเฟกต์)")
    return {"xi-api-key": key, "Content-Type": "application/json"}


def get_total_narration_seconds(job_dir: Path) -> float:
    """รวมความยาวเสียงพากย์ทุก scene จาก Step 2 เพื่อกะความยาวเพลงพื้นหลัง"""
    scene_files = sorted((job_dir / "audio").glob("scene_*.mp3"))
    if not scene_files:
        return 35.0  # ค่า fallback ถ้ายังไม่มีไฟล์เสียงพากย์
    total_ms = sum(len(AudioSegment.from_mp3(f)) for f in scene_files)
    return total_ms / 1000


def generate_background_music(slug: str, prompt: str, length_ms: int, out_path: Path) -> None:
    length_ms = max(3000, min(600000, length_ms))  # API จำกัด 3 วิ - 5 นาที
    resp = requests.post(
        MUSIC_ENDPOINT,
        headers=_headers(),
        json={
            "prompt": prompt,
            "music_length_ms": length_ms,
            "model_id": "music_v2",
            "force_instrumental": True,  # กันไม่ให้มีเสียงร้องมาแย่งเสียงพากย์ข่าว
        },
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)

    cost = (length_ms / 1000 / 60) * 0.15  # music_v2 = $0.15 ต่อนาที
    log_usage(slug, "music", "music_v2", out_path.name, cost, f"{length_ms}ms")


def generate_sound_effect(slug: str, text: str, out_path: Path, duration_seconds: float = None) -> None:
    body = {"text": text}
    if duration_seconds:
        body["duration_seconds"] = duration_seconds
    resp = requests.post(SFX_ENDPOINT, headers=_headers(), json=body)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)

    billed_seconds = duration_seconds or 2.0  # ถ้าไม่ระบุ ระบบ auto-เลือกความยาว ใช้ค่าประมาณ
    cost = (billed_seconds / 60) * 0.12  # eleven_text_to_sound_v2 = $0.12 ต่อนาที
    log_usage(slug, "sfx", "eleven_text_to_sound_v2", out_path.name, cost, f"~{billed_seconds}s")


def run(job_dir_str: str) -> Path:
    job_dir = Path(job_dir_str)
    bg_dir = job_dir / "audio_bg"
    bg_dir.mkdir(exist_ok=True)

    total_sec = get_total_narration_seconds(job_dir)
    music_length_ms = int((total_sec + 1.5) * 1000)  # เผื่อ intro/outro เล็กน้อย

    slug = job_dir.name

    print(f"[1/2] สร้างเพลงพื้นหลัง ~{total_sec:.1f} วิ ด้วย ElevenLabs Music ...")
    music_prompt = (
        "Tense, cautionary news-report background music for a public-health warning "
        "short video, minimal piano and low strings, building suspense, instrumental only, "
        "no vocals, suitable to sit quietly under a spoken narration track"
    )
    generate_background_music(slug, music_prompt, music_length_ms, bg_dir / "music.mp3")

    print("[2/2] สร้างเสียงเอฟเฟกต์จุดเน้น ด้วย ElevenLabs Sound Effects ...")
    generate_sound_effect(
        slug,
        "Sharp attention-grabbing alert notification ding, short and clean",
        bg_dir / "sfx_hook.mp3",
        duration_seconds=1.5,
    )
    generate_sound_effect(
        slug,
        "Deep dramatic tension riser leading into a soft warning beep",
        bg_dir / "sfx_warning.mp3",
        duration_seconds=2.0,
    )

    print(f"\nเสร็จแล้ว -> {bg_dir}/")
    print("หมายเหตุ: ตอนรวมคลิป (Step 4) ให้ลดวอลุ่มเพลงพื้นหลังเหลือ ~-18dB")
    print("ใต้เสียงพากย์ และวาง sfx_hook ที่ scene 1, sfx_warning ที่ scene สุดท้าย")
    print_cost_summary(slug)
    return bg_dir


if __name__ == "__main__":
    job_dir_arg = sys.argv[1] if len(sys.argv) > 1 else "output/20260920-rabies-plapak"
    run(job_dir_arg)
