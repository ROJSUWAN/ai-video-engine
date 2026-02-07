# ---------------------------------------------------------
import sys
sys.stdout.reconfigure(line_buffering=True)
# ---------------------------------------------------------

from flask import Flask, request, jsonify
import threading
import uuid
import os
import time
import requests
import cloudscraper
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio
import gc
import random # ✅ เพิ่มตัวสุ่ม

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Webhook URL (อันเดิม)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# --- Helper Functions ---

def get_font(fontsize):
    font_names = ["tahoma.ttf", "arial.ttf", "leelawad.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    linux_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def create_placeholder_image(filename, text="No Image"):
    img = Image.new('RGB', (1080, 1920), color=(30, 30, 30))
    d = ImageDraw.Draw(img)
    try:
        f = get_font(60)
        d.text((100, 900), text, fill=(255, 100, 100), font=f)
    except: pass
    img.save(filename)

def download_image(url, filename):
    """🔥 โหลดรูปเวอร์ชันอัปเกรด (Flux + Backup Plans)"""
    
    # 1. ปรับจูน URL ของ Pollinations ให้ใช้โมเดลใหม่ (Flux) และสุ่ม Seed
    if "pollinations.ai" in url:
        sep = "&" if "?" in url else "?"
        # เพิ่ม model=flux, ขนาดภาพแนวตั้ง, และ seed สุ่ม (แก้ปัญหา Cache)
        url += f"{sep}model=flux&width=720&height=1280&seed={random.randint(0, 99999)}"
        
    print(f"⬇️ Downloading: {url[:60]}...")
    
    # สร้าง Scraper
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    
    # --- แผน A: พยายามโหลดจาก AI (3 รอบ) ---
    for attempt in range(3):
        try:
            response = scraper.get(url, timeout=20)
            if response.status_code == 200:
                with open(filename, 'wb') as f: f.write(response.content)
                # เช็คไฟล์
                Image.open(filename).verify()
                Image.open(filename).convert('RGB').save(filename)
                print("✅ AI Image Downloaded!")
                return True
            else:
                print(f"⚠️ AI Status: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Retry {attempt+1}: {e}")
            time.sleep(2)

    # --- แผน B: ถ้า AI พัง ให้ใช้ภาพวิวสวยๆ แทน (ดีกว่าจอดำ) ---
    print("⚠️ AI Failed (502/Block). Switching to Plan B (Random Photo)...")
    try:
        # ใช้ Picsum (ฟรีและไม่บล็อก)
        backup_url = f"https://picsum.photos/720/1280?random={random.randint(0, 1000)}"
        response = requests.get(backup_url, timeout=20)
        if response.status_code == 200:
            with open(filename, 'wb') as f: f.write(response.content)
            Image.open(filename).convert('RGB').save(filename)
            print("✅ Backup Image Used!")
            return True
    except Exception as e:
        print(f"❌ Backup Failed: {e}")

    return False

# ... (ส่วนสร้างเสียง create_voice_safe เหมือนเดิม) ...
async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try:
            tts = gTTS(text=text, lang='th')
            tts.save(filename)
        except: pass

# ... (ส่วนสร้าง Text Clip เหมือนเดิม) ...
def create_text_clip(text, size=(1080, 1920), duration=5):
    fontsize = 50
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    font = get_font(fontsize)
    lines = []
    temp_line = ""
    for word in text.split(' '):
        if len(temp_line + word) < 25: temp_line += word + " "
        else:
            lines.append(temp_line)
            temp_line = word + " "
    lines.append(temp_line)
    text_height = len(lines) * 70
    start_y = 1400 
    overlay = Image.new('RGBA', size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([50, start_y - 20, 1030, start_y + text_height + 20], fill=(0,0,0,160))
    img = Image.alpha_composite(img, overlay)
    draw_text = ImageDraw.Draw(img)
    cur_y = start_y
    for line in lines:
        try: draw_text.text((80, cur_y), line, font=font, fill="white")
        except: pass
        cur_y += 70
    return ImageClip(np.array(img)).set_duration(duration)

# ... (ส่วน Upload เหมือนเดิม) ...
def upload_to_temp_host(filename):
    try:
        print(f"☁️ Uploading {filename}...")
        with open(filename, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if response.status_code == 200:
                url = response.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Link: {url}")
                return url
    except Exception as e:
        print(f"❌ Upload Error: {e}")
    return None

# ... (ส่วน Process Video หลัก เหมือนเดิมเป๊ะ) ...
def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting (Bulletproof Mode)...")
    output_filename = f"video_{task_id}.mp4"
    temp_files = []
    
    try:
        clip_files = []
        for i, scene in enumerate(scenes):
            print(f"[{task_id}] Processing Scene {i+1}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"
            
            temp_files.extend([img_file, audio_file])
            clip_files.append(clip_output)

            # 1. Download Image (ใช้ฟังก์ชันใหม่)
            if not download_image(scene['image_url'], img_file):
                 print(f"⚠️ Everything Failed, using placeholder")
                 create_placeholder_image(img_file, f"Scene {i+1}")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # 2. Render Small Clip
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5 
                    
                    img_clip = ImageClip(img_file).set_duration(dur)
                    if img_clip.w / img_clip.h > 9/16:
                        img_clip = img_clip.resize(height=1920).crop(x_center=img_clip.w/2, width=1080)
                    else:
                        img_clip = img_clip.resize(width=1080).crop(y_center=img_clip.h/2, height=1920)
                    
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
                    
                    video.write_videofile(
                        clip_output, fps=15, codec='libx264', audio_codec='aac', 
                        preset='ultrafast', threads=2, logger=None
                    )
                    
                    video.close()
                    del video, img_clip, txt_clip, audio
                    gc.collect() 
                    
                except Exception as e: 
                    print(f"❌ Error Scene {i}: {e}")

        # 3. Concatenate
        if clip_files:
            print(f"[{task_id}] 🎞️ Merging clips...")
            clips = [VideoFileClip(c) for c in clip_files]
            final = concatenate_videoclips(clips, method="compose")
            
            final.write_videofile(
                output_filename, fps=15, codec='libx264', audio_codec='aac', 
                preset='ultrafast', threads=2
            )
            
            # 4. Upload & Send
            video_url = upload_to_temp_host(output_filename)
            if video_url:
                print(f"[{task_id}] 🚀 Sending Webhook...")
                requests.post(N8N_WEBHOOK_URL, json={
                    'task_id': task_id, 'status': 'success', 'video_url': video_url
                })
            
            final.close()
            for c in clips: c.close()
            
    except Exception as e:
        print(f"[{task_id}] Error: {e}")
    finally:
        try:
            for f in os.listdir():
                if f.startswith(f"clip_{task_id}") or f.startswith(f"temp_{task_id}") or f.startswith(f"video_{task_id}"):
                    try: os.remove(f)
                    except: pass
        except: pass

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    scenes = data.get('scenes', [])
    task_id = str(uuid.uuid4())
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes))
    thread.start()
    return jsonify({"status": "processing", "task_id": task_id}), 202

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)