from flask import Flask, request, jsonify, send_file
import os
import uuid
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import requests
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio

# ✅ แก้ปัญหา Event Loop ชนกันใน Flask (สำคัญมาก)
nest_asyncio.apply()

app = Flask(__name__)

# --- Helper Functions ---

def get_font(fontsize):
    """หาฟอนต์ภาษาไทยที่ใช้ได้ ทั้งบน Windows และ Linux"""
    # 1. หา Tahoma ที่เราอาจจะอัปโหลดไป
    if os.path.exists("tahoma.ttf"):
        return ImageFont.truetype("tahoma.ttf", fontsize)
    
    # 2. หาฟอนต์มาตรฐาน Linux (เช่นใน Railway)
    linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
    for path in linux_fonts:
        if os.path.exists(path):
            return ImageFont.truetype(path, fontsize)
            
    # 3. ถ้าไม่เจอเลย ใช้ Default (อ่านไทยไม่ออกแต่ไม่ Error)
    print("⚠️ หาฟอนต์ไม่เจอ! ใช้ฟอนต์ Default")
    return ImageFont.load_default()

def download_image(url, filename):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            # ✅ เช็คว่าเป็นรูปจริงไหม (กัน Unsplash ส่ง HTML มาหลอก)
            try:
                img = Image.open(filename).convert('RGB')
                img.save(filename)
                return True
            except:
                print(f"❌ URL นี้ไม่ใช่รูปภาพ (อาจเป็นเว็บ): {url}")
                return False
    except Exception as e:
        print(f"💥 Error โหลดรูป: {e}")
    return False

async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except Exception as e:
        print(f"⚠️ Edge TTS พลาด ({e}) -> ใช้ Google TTS แทน")
        tts = gTTS(text=text, lang='th')
        tts.save(filename)

def create_text_clip(text, size=(1080, 1920), duration=5):
    fontsize = 50
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    font = get_font(fontsize)
    
    # จัดการข้อความ
    draw = ImageDraw.Draw(img)
    
    # (โค้ดจัดบรรทัดแบบย่อ เพื่อความกระชับ)
    max_width = size[0] - 100
    lines = []
    for line in text.split('\n'):
        temp_line = ""
        for char in line:
            if draw.textlength(temp_line + char, font=font) <= max_width:
                temp_line += char
            else:
                lines.append(temp_line)
                temp_line = char
        lines.append(temp_line)

    # วาดพื้นหลังและข้อความ
    text_height = len(lines) * (fontsize * 1.5)
    start_y = size[1] - text_height - 200
    
    overlay = Image.new('RGBA', size, (0,0,0,0))
    d_overlay = ImageDraw.Draw(overlay)
    d_overlay.rectangle([50, start_y - 20, size[0]-50, start_y + text_height + 20], fill=(0,0,0,160))
    img = Image.alpha_composite(img, overlay)
    
    d_final = ImageDraw.Draw(img)
    cur_y = start_y
    for line in lines:
        w = d_final.textlength(line, font=font)
        d_final.text(((size[0]-w)/2, cur_y), line, font=font, fill="white")
        cur_y += (fontsize * 1.5)
        
    return ImageClip(np.array(img)).set_duration(duration)

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    print(f"\n📩 ได้รับงาน: {len(data.get('scenes', []))} ฉาก")
    
    scenes = data.get('scenes', [])
    if not scenes: return jsonify({"error": "No scenes"}), 400

    task_id = str(uuid.uuid4())
    output_filename = f"final_{task_id}.mp4"
    clips = []
    temp_files = []

    try:
        for i, scene in enumerate(scenes):
            print(f"--- เริ่มฉากที่ {i+1} ---")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            temp_files.extend([img_file, audio_file])

            # 1. โหลดรูป
            if not download_image(scene['image_url'], img_file):
                print(f"⚠️ ข้ามฉาก {i+1}: โหลดรูปไม่ผ่าน")
                continue

            # 2. สร้างเสียง
            # ใช้ loop ใหม่เพื่อป้องกันการชนกับ Flask
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))
            
            if not os.path.exists(audio_file):
                print(f"⚠️ ข้ามฉาก {i+1}: สร้างเสียงไม่ได้")
                continue

            # 3. ตัดต่อ
            audio = AudioFileClip(audio_file)
            dur = audio.duration + 0.5
            
            img_clip = ImageClip(img_file).set_duration(dur)
            # Resize ให้เต็มจอ (Center Crop)
            if img_clip.w / img_clip.h > 9/16:
                img_clip = img_clip.resize(height=1920)
                img_clip = img_clip.crop(x_center=img_clip.w/2, width=1080)
            else:
                img_clip = img_clip.resize(width=1080)
                img_clip = img_clip.crop(y_center=img_clip.h/2, height=1920)

            txt_clip = create_text_clip(scene['script'], duration=dur)
            video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
            clips.append(video)
            print(f"✅ ฉาก {i+1} เสร็จสมบูรณ์")

        if not clips:
            return jsonify({"message": "ไม่สามารถสร้างคลิปได้เลย (ตรวจสอบ URL รูปภาพ หรือ ระบบเสียง)"}), 500

        print("🎞️ กำลัง Render รวม...")
        final = concatenate_videoclips(clips)
        # ลด FPS เหลือ 15 เพื่อความเร็วและประหยัด RAM บน Cloud
        final.write_videofile(output_filename, fps=15, codec='libx264', audio_codec='aac')
        
        return send_file(output_filename, mimetype='video/mp4')

    except Exception as e:
        print(f"💥 Critical Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # ล้างขยะ
        for f in temp_files:
            if os.path.exists(f): os.remove(f)
        if os.path.exists(output_filename): os.remove(output_filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)