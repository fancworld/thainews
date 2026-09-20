# ใช้ Docker แทน native Python buildpack ของ Render เพราะ pydub ต้องมี ffmpeg
# (Render native Python ไม่มี ffmpeg ติดตั้งมาให้)
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --server.headless true กันไม่ให้ Streamlit หยุดรอถาม email ตอน first-run (ไม่มี TTY ใน
# container เลยค้างตลอดจนแอปไม่มีวันพร้อม - เป็นสาเหตุจริงที่ทำให้ Render ค้างที่หน้า "waking up")
# Render กำหนด PORT ผ่าน env var มาให้เอง (ห้าม hardcode เป็น 8501)
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
CMD streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true
