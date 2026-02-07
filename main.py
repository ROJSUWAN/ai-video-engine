from flask import Flask, request, jsonify
import threading
import uuid
import os
import time
import requests
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio

# ✅ แก้ปัญหา Asyncio loop ตีกัน
nest_asyncio.apply()

app = Flask(__name__)

# ==========================================
# 🔗 ตั้งค่า Webhook (จุดที่ Python จะส่งไฟล์กลับไป)
# ==========================================
# URL นี้มาจากที่คุณตั้งค่าไว้ใน n8n (โหมด Test)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# --- 🛠️ Helper Functions ---

def get_font(fontsize):
    """หาฟอนต์ภาษาไทย (รองรับทั้ง Windows/Linux)"""
    # 1. ลองหาในโฟลเดอร์โปรเจกต์
    font_names = ["tahoma.ttf", "arial.ttf", "leelawad.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    
    # 2. ลองหาใน System Linux
    linux_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
            
    return ImageFont.load_default()

def create_placeholder_image(filename, text="No Image"):
    """สร้างภาพดำสำรอง กรณีโหลดรูปไม่ได้"""
    img = Image.new('RGB', (1080, 1920), color=(30, 30, 30))
    d = ImageDraw.Draw(img)
    try:
        f = get_font(80)
        # วาดข้อความกลางจอ
        text_w = d.textlength(text, font=f)
        d.text(((1080-text_w)/2, 900), text, fill=(200, 200, 200), font=f)
    except:
        pass
    img.save(filename)

def download_image(url, filename):
    """โหลดรูปพร้อมระบบ Retry"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # ลองโหลด 3 ครั้ง (ครั้งละ 15 วินาที)
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    # เช็คว่าไฟล์รูปสมบูรณ์ไหม
                    try:
                        img = Image.open(filename)
                        img.verify() # ตรวจสอบไฟล์
                        # แปลงเป็น RGB เพื่อความชัวร์ (แก้บั๊ก PNG/WebP)
                        img = Image.open(filename).convert('RGB')
                        img.save(filename)
                        return True
                    except:
                        pass
            except:
                time.sleep(2)
        return False
    except:
        return False

async def create_voice_safe(text, filename):
    """สร้างเสียง (EdgeTTS -> Fallback gTTS)"""
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try:
            tts = gTTS(text=text, lang='th')
            tts.save(filename)
        except:
            pass

def create_text_clip(text, size=(1080, 1920), duration=5):
    """สร้าง Subtitle ด้านล่าง"""
    fontsize = 50
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    font = get_font(fontsize)
    
    # ตัดคำแบบง่าย (25 ตัวอักษรต่อบรรทัด)
    lines = []
    temp_line = ""
    for word in text.split(' '):
        if len(temp_line + word) < 25:
            temp_line += word + " "
        else:
            lines.append(temp_line)
            temp_line = word + " "
    lines.append(temp_line)

    # วาดพื้นหลัง
    text_height = len(lines) * 70
    start_y = 1450 # ตำแหน่งด้านล่าง
    
    overlay = Image.new('RGBA', size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    # กล่องดำจางๆ
    draw.rectangle([50, start_y - 20, 1030, start_y + text_height + 20], fill=(0,0,0,160))
    img = Image.alpha_composite(img, overlay)
    
    draw_text = ImageDraw.Draw(img)
    cur_y = start_y
    for line in lines:
        # จัดกึ่งกลาง
        try:
            w = draw_text.textlength(line, font=font)
        except:
            w = 0
        draw_text.text(((size[0]-w)/2, cur_y), line, font=font, fill="white")
        cur_y += 70
        
    return ImageClip(np.array(img)).set_duration(duration)

def process_video_background(task_id, scenes):
    """⚙️ โรงงานผลิตวิดีโอ (รันเบื้องหลัง)"""
    print(f"[{task_id}] 🚀 เริ่มงาน Background Process...")
    output_filename = f"video_{task_id}.mp4"
    temp_files = []
    
    try:
        clips = []
        for i, scene in enumerate(scenes):
            print(f"[{task_id}] กำลังทำฉากที่ {i+1}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            temp_files.extend([img_file, audio_file])

            # 1. Download Image (ถ้าพลาด ใช้ภาพ Placeholder)
            if not download_image(scene['image_url'], img_file):
                 print(f"[{task_id}] ⚠️ โหลดรูปไม่ได้ ใช้ภาพสำรองแทน")
                 create_placeholder_image(img_file, f"Image Error: Scene {i+1}")

            # 2. Create Audio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # 3. Combine
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5 
                    
                    img_clip = ImageClip(img_file).set_duration(dur)
                    
                    # Resize & Crop (9:16)
                    if img_clip.w / img_clip.h > 9/16:
                        img_clip = img_clip.resize(height=1920)
                        img_clip = img_clip.crop(x_center=img_clip.w/2, width=1080)
                    else:
                        img_clip = img_clip.resize(width=1080)
                        img_clip = img_clip.crop(y_center=img_clip.h/2, height=1920)
                    
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
                    clips.append(video)
                except Exception as e:
                    print(f"[{task_id}] ❌ Error ฉากที่ {i+1}: {e}")

        if clips:
            print(f"[{task_id}] 🎞️ กำลัง Render รวม ({len(clips)} ฉาก)...")
            final = concatenate_videoclips(clips)
            # Render คุณภาพดี (fps 24) เพราะไม่ต้องรีบแล้ว
            final.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac', logger=None)
            
            # ✅ ส่งไฟล์กลับไปที่ n8n Webhook
            print(f"[{task_id}] ✅ เสร็จสมบูรณ์! กำลังส่งไฟล์กลับ...")
            if os.path.exists(output_filename):
                with open(output_filename, 'rb') as f:
                    # ส่งไฟล์แบบ Multipart/Form-data
                    try:
                        files = {'file': (output_filename, f, 'video/mp4')}
                        data = {'task_id': task_id, 'status': 'success'}
                        r = requests.post(N8N_WEBHOOK_URL, files=files, data=data, timeout=60)
                        print(f"[{task_id}] 📡 ส่ง Webhook: Status {r.status_code}")
                    except Exception as e:
                        print(f"[{task_id}] ❌ ส่ง Webhook ไม่ผ่าน: {e}")
        else:
            print(f"[{task_id}] ❌ ไม่สามารถสร้างคลิปได้เลย")
            requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'error', 'message': 'No clips created'})

    except Exception as e:
        print(f"[{task_id}] 💥 Critical Error: {e}")
        requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'error', 'message': str(e)})

    finally:
        # ล้างไฟล์ขยะ
        print(f"[{task_id}] 🧹 Cleaning up...")
        for f in temp_files:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass
        if os.path.exists(output_filename): 
            try: os.remove(output_filename)
            except: pass

@app.route('/create-video', methods=['POST'])
def api_create_video():
    """API จุดรับงาน (รับแล้วตอบกลับทันที)"""
    data = request.json
    scenes = data.get('scenes', [])
    
    if not scenes: return jsonify({"error": "No scenes"}), 400

    task_id = str(uuid.uuid4())
    print(f"📩 ได้รับคำสั่งใหม่: ID {task_id} ({len(scenes)} ฉาก)")
    
    # 🔥 สั่งรันเบื้องหลังทันที (Threading)
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes))
    thread.start()

    # ตอบกลับ n8n ทันทีว่า "รับงานแล้ว" (ไม่ต้องรอเสร็จ)
    return jsonify({
        "status": "processing",
        "message": "รับงานแล้ว! กำลังทำเบื้องหลัง เสร็จแล้วจะส่งไปที่ Webhook",
        "task_id": task_id
    }), 202

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)