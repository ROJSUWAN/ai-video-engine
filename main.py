from flask import Flask, request, jsonify, send_file
import os
import uuid
import time
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import requests
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio

# ✅ แก้ปัญหา Event Loop ชนกัน
nest_asyncio.apply()

app = Flask(__name__)

# --- Helper Functions ---

def get_font(fontsize):
    """หาฟอนต์ภาษาไทย"""
    font_names = ["tahoma.ttf", "leelawad.ttf", "arial.ttf"]
    # ลองหาในโฟลเดอร์ปัจจุบันก่อน
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    
    # ลองหาใน System Fonts ของ Linux
    linux_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
            
    return ImageFont.load_default()

def create_placeholder_image(filename, text="Image Failed"):
    """สร้างภาพสำรองกรณีโหลดรูปไม่ได้"""
    img = Image.new('RGB', (1080, 1920), color=(50, 50, 50))
    d = ImageDraw.Draw(img)
    try:
        f = get_font(100)
        d.text((100, 900), text, fill=(255, 100, 100), font=f)
    except:
        pass
    img.save(filename)

def download_image(url, filename, logs):
    try:
        # ✅ เพิ่ม Timeout เป็น 60 วินาที และปลอมตัวเนียนขึ้น
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # ลองโหลด 3 ครั้ง (Retry)
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=60)
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    # เช็คไฟล์
                    img = Image.open(filename).convert('RGB')
                    img.save(filename)
                    return True
            except Exception as e:
                logs.append(f"   ⚠️ Retry {attempt+1}: {str(e)}")
                time.sleep(2)
        
        logs.append(f"   ❌ โหลดรูปไม่ผ่านจริงๆ: {url}")
        return False

    except Exception as e:
        logs.append(f"   💥 Error Download: {str(e)}")
        return False

async def create_voice_safe(text, filename, logs):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except Exception as e:
        logs.append(f"   ⚠️ EdgeTTS Error: {e}")
        try:
            tts = gTTS(text=text, lang='th')
            tts.save(filename)
        except Exception as ge:
            logs.append(f"   ❌ gTTS Error: {ge}")

def create_text_clip(text, size=(1080, 1920), duration=5):
    fontsize = 50
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    font = get_font(fontsize)
    
    # จัดการข้อความ (Word Wrap แบบง่าย)
    lines = []
    temp_line = ""
    max_chars = 30 # ประมาณเอาเพื่อความเร็ว
    for word in text.split(' '):
        if len(temp_line + word) < max_chars:
            temp_line += word + " "
        else:
            lines.append(temp_line)
            temp_line = word + " "
    lines.append(temp_line)

    # วาดพื้นหลัง
    text_height = len(lines) * 80
    start_y = 1500 # ตำแหน่งด้านล่าง
    
    overlay = Image.new('RGBA', size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([50, start_y - 20, 1030, start_y + text_height + 20], fill=(0,0,0,180))
    img = Image.alpha_composite(img, overlay)
    
    # วาดข้อความ
    draw_text = ImageDraw.Draw(img)
    cur_y = start_y
    for line in lines:
        draw_text.text((80, cur_y), line, font=font, fill="white")
        cur_y += 80
        
    return ImageClip(np.array(img)).set_duration(duration)

@app.route('/create-video', methods=['POST'])
def api_create_video():
    logs = [] # ✅ เก็บ Log ไว้ส่งกลับไปให้ n8n ดู
    try:
        data = request.json
        scenes = data.get('scenes', [])
        
        task_id = str(uuid.uuid4())
        output_filename = f"final_{task_id}.mp4"
        clips = []
        temp_files = []

        for i, scene in enumerate(scenes):
            logs.append(f"🎬 กำลังทำฉากที่ {i+1}")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            temp_files.extend([img_file, audio_file])

            # 1. โหลดรูป (ถ้าพัง ให้ใช้ภาพสำรอง แทนที่จะ Error)
            if not download_image(scene['image_url'], img_file, logs):
                logs.append(f"   ⚠️ ใช้ภาพ Placeholder แทน")
                create_placeholder_image(img_file, f"Image Error: Scene {i+1}")

            # 2. สร้างเสียง
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file, logs))
            
            if not os.path.exists(audio_file):
                logs.append(f"   ❌ สร้างเสียงไม่ผ่าน ข้ามฉากนี้")
                continue

            # 3. รวมร่าง
            try:
                audio = AudioFileClip(audio_file)
                dur = audio.duration + 0.5
                img_clip = ImageClip(img_file).set_duration(dur)
                
                # Resize
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
                logs.append(f"   ❌ ตัดต่อพัง: {e}")

        if not clips:
            return jsonify({"status": "error", "logs": logs, "message": "ไม่สำเร็จสักฉาก"}), 500

        logs.append("🎞️ กำลัง Render...")
        final = concatenate_videoclips(clips)
        final.write_videofile(output_filename, fps=15, codec='libx264', audio_codec='aac')
        
        return send_file(output_filename, mimetype='video/mp4')

    except Exception as e:
        return jsonify({"status": "critical_error", "error": str(e), "logs": logs}), 500
    finally:
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        if os.path.exists(output_filename): os.remove(output_filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)