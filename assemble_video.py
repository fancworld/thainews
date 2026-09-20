"""
Step 4: รวมคลิป ด้วย JSON2Video API
================================================================
Input  : output/<slug>/  (ผลลัพธ์จาก Step 2 + Step 3)
           script.json, audio/scene_N.mp3, images/scene_N.png,
           audio_bg/music.mp3, audio_bg/sfx_hook.mp3, audio_bg/sfx_warning.mp3
Output : output/<slug>/final_912.mp4   (แนวตั้ง 1080x1920)

ปัญหาที่ต้องแก้ก่อน: JSON2Video ดึงไฟล์จาก "URL สาธารณะ" เท่านั้น ไม่รับไฟล์
จากเครื่องเราตรงๆ จึงต้องอัปโหลดรูป/เสียงทุกไฟล์ขึ้นที่เก็บสาธารณะก่อน
สคริปต์นี้ใช้ Cloudinary (ฟรี, มี Python SDK, เหมาะกับงานนี้ที่สุด)

ติดตั้ง : pip install cloudinary requests --break-system-packages
ตั้งค่า  : export CLOUDINARY_URL="cloudinary://<key>:<secret>@<cloud_name>"
          export JSON2VIDEO_API_KEY="..."
รัน     : python assemble_video.py output/20260920-rabies-plapak

อ้างอิง API (เช็ค docs ล่าสุดก่อนใช้จริงจัง):
  Create movie : POST https://api.json2video.com/v2/movies
  Check status : GET  https://api.json2video.com/v2/movies?project=<id>
"""

import json
import os
import sys
import time
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from pydub import AudioSegment

from cost_logger import log_usage, print_cost_summary

J2V_BASE = "https://api.json2video.com/v2/movies"

_cloudinary_configured = False


def _ensure_cloudinary_configured() -> None:
    """ตั้งค่า Cloudinary แบบ lazy (ตอนใช้จริง ไม่ใช่ตอน import ไฟล์นี้) กัน error ทำเว็บแอปพังทั้งหน้า
    ตั้งแต่โหลดครั้งแรก ทั้งที่ผู้ใช้อาจแค่อยากทดสอบ Step 2/3 ที่ยังไม่เกี่ยวกับ Cloudinary เลย"""
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    cloudinary_url = os.environ.get("CLOUDINARY_URL")
    if not cloudinary_url:
        raise RuntimeError("ยังไม่ได้ตั้ง CLOUDINARY_URL - export/setx ก่อนใช้ Step 4 (รวมคลิป)")
    cloudinary.config(cloudinary_url=cloudinary_url)
    _cloudinary_configured = True


def _get_j2v_api_key() -> str:
    key = os.environ.get("JSON2VIDEO_API_KEY")
    if not key:
        raise RuntimeError("ยังไม่ได้ตั้ง JSON2VIDEO_API_KEY - export/setx ก่อนใช้ Step 4 (รวมคลิป)")
    return key


def upload(path: Path, resource_type: str = "auto") -> str:
    """อัปโหลดไฟล์ขึ้น Cloudinary แล้วคืน public URL สำหรับ JSON2Video ดึงไปใช้"""
    _ensure_cloudinary_configured()
    result = cloudinary.uploader.upload(str(path), resource_type=resource_type)
    return result["secure_url"]


def build_movie_json(job_dir: Path) -> dict:
    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    scenes_data = script["scenes"]

    scenes = []
    scene_durations = []

    for i, scene in enumerate(scenes_data, start=1):
        img_path = job_dir / "images" / f"scene_{i}.png"
        audio_path = job_dir / "audio" / f"scene_{i}.mp3"

        duration_sec = len(AudioSegment.from_mp3(audio_path)) / 1000
        scene_durations.append(duration_sec)

        img_url = upload(img_path, resource_type="image")
        narration_url = upload(audio_path, resource_type="video")  # mp3 = resource_type video ใน Cloudinary

        scenes.append(
            {
                "comment": f"Scene {i}",
                "duration": -1,  # ยืดตามความยาวเสียงพากย์ในฉากอัตโนมัติ
                "elements": [
                    {
                        "type": "image",
                        "src": img_url,
                        "duration": -1,
                        "resize": "cover",
                        "zoom": 2,
                        "pan": "right" if i % 2 else "left",  # สลับทิศ pan กันภาพดูนิ่งเกินไป
                    },
                    {"type": "audio", "src": narration_url, "duration": -1, "volume": 1},
                    {
                        "type": "subtitles",
                        "language": "th",
                        "model": "whisper",  # เผื่อความแม่นยำภาษาไทยดีกว่า default
                        "settings": {
                            "style": "boxed-word",
                            "font-family": "Noto Sans Thai",
                            "font-size": 64,
                            "word-color": "#FFD400",
                            "line-color": "#FFFFFF",
                            "outline-color": "#000000",
                            "outline-width": 2,
                            "position": "bottom-center",
                            "max-words-per-line": 4,
                        },
                    },
                ],
            }
        )

    music_url = upload(job_dir / "audio_bg" / "music.mp3", resource_type="video")
    sfx_hook_url = upload(job_dir / "audio_bg" / "sfx_hook.mp3", resource_type="video")
    sfx_warning_url = upload(job_dir / "audio_bg" / "sfx_warning.mp3", resource_type="video")

    time_before_last_scene = sum(scene_durations[:-1])

    movie = {
        "resolution": "instagram-story",  # preset แนวตั้ง 1080x1920 (9:16)
        "quality": "high",
        "scenes": scenes,
        "elements": [
            {
                "type": "audio",
                "src": music_url,
                "start": 0,
                "duration": -2,  # ยืด/ตัดให้พอดีความยาวคลิปทั้งเรื่องอัตโนมัติ
                "loop": -1,
                "volume": 0.2,  # เบาลงให้ไม่ตีกับเสียงพากย์
                "fade-out": 1.5,
            },
            {"type": "audio", "src": sfx_hook_url, "start": 0, "duration": -1, "volume": 1},
            {
                "type": "audio",
                "src": sfx_warning_url,
                "start": round(time_before_last_scene, 2),
                "duration": -1,
                "volume": 1,
            },
        ],
        "exports": [{"destinations": []}],
    }
    return movie


def render(slug: str, movie_json: dict) -> str:
    """ส่ง JSON ไปสร้างคลิป แล้ว poll สถานะจนกว่าจะ done คืนค่า URL วิดีโอสุดท้าย"""
    j2v_api_key = _get_j2v_api_key()
    resp = requests.post(
        J2V_BASE,
        headers={"x-api-key": j2v_api_key, "Content-Type": "application/json"},
        json=movie_json,
    )
    resp.raise_for_status()
    project_id = resp.json()["project"]
    print(f"  ส่งคำขอ render แล้ว project={project_id} กำลังรอ...")

    while True:
        time.sleep(5)
        status_resp = requests.get(
            J2V_BASE, headers={"x-api-key": j2v_api_key}, params={"project": project_id}
        )
        movie_status = status_resp.json()["movie"]
        if movie_status["status"] == "done":
            duration = movie_status.get("duration", 0)
            credits = duration  # 1 credit = 1 วิ (HD)
            cost = credits * (16.95 / 3000)  # อิงเรทแพลน Hobby - ปรับตามแพลนจริงที่ใช้
            log_usage(slug, "render", "json2video", "final movie render", cost,
                       f"{duration:.1f}s = {credits:.0f} credits")
            return movie_status["url"]
        if movie_status["status"] == "error":
            raise RuntimeError(f"JSON2Video render ล้มเหลว: {movie_status}")
        print(f"  สถานะ: {movie_status['status']} ...")


def run(job_dir_str: str) -> Path:
    job_dir = Path(job_dir_str)
    slug = job_dir.name

    print("[1/3] อัปโหลด asset ทั้งหมดขึ้น Cloudinary และประกอบ JSON ...")
    movie_json = build_movie_json(job_dir)
    (job_dir / "movie_request.json").write_text(
        json.dumps(movie_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_usage(slug, "hosting", "cloudinary", "upload assets", 0.0, "free tier ปกติ ไม่เกินโควตา")

    print("[2/3] ส่งให้ JSON2Video render ...")
    video_url = render(slug, movie_json)

    print("[3/3] ดาวน์โหลดคลิปสุดท้าย ...")
    out_path = job_dir / "final_912.mp4"
    video_bytes = requests.get(video_url).content
    out_path.write_bytes(video_bytes)

    print(f"\nเสร็จแล้ว -> {out_path}")
    print_cost_summary(slug)
    return out_path


if __name__ == "__main__":
    job_dir_arg = sys.argv[1] if len(sys.argv) > 1 else "output/20260920-rabies-plapak"
    run(job_dir_arg)
