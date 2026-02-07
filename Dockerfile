FROM python:3.9-slim

# 1. ติดตั้ง FFmpeg และระบบจัดการ Font
RUN apt-get update && \
    apt-get install -y ffmpeg libsm6 libxext6 fontconfig && \
    rm -rf /var/lib/apt/lists/*

# 2. ตั้งค่าพื้นที่ทำงาน
WORKDIR /app

# 3. ลง Library Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. ก๊อปปี้โค้ดและไฟล์ Font ทั้งหมดขึ้นไป
COPY . .

# 5. เปิด Port 8080
EXPOSE 8080

# 6. คำสั่งรัน
CMD ["python", "main.py"]