# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (Auto-Fix Keys: script/caption)
# ---------------------------------------------------------
import sys
# บังคับให้ Python พ่น Log ออกมาทันที (เพื่อดู Logs ใน Railway)
sys.stdout.reconfigure(line_buffering=True)

import os
import threading
import uuid
import time
import requests
import asyncio
import nest_asyncio
import gc
import json
import numpy as np
from flask import Flask, request, jsonify

# AI & Media Libs
from duckduckgo_search import DDGS
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import edge_tts
from gtts import gTTS

# Google Cloud
from google.cloud import storage
import datetime

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Config
# ✅ แก้ไข URL Webhook ตามที่คุณระบุ
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/video-completed"

# Environment Variables
HF_TOKEN = os.environ.get("HF_TOKEN")

# ⚙️ Google Cloud Storage Config
BUCKET_NAME = "n8n-video-storage-0123"  # <-- ชื่อ Bucket ของคุณ
KEY_FILE_PATH = "gcs_key.json"        # <-- ชื่อไฟล์ Key (สำหรับ Local)

# ---------------------------------------------------------
# ☁️ Upload Function (Secure Version)
# ---------------------------------------------------------
def get_gcs_client():
    """สร้าง Client โดยดูว่ามาจาก File หรือ Env Variable"""
    gcs_json_content = os.environ.get("GCS_KEY_JSON")
    if gcs_json_content:
        try:
            # print("🔑 Authenticating using Environment Variable...")
            info = json.loads(gcs_json_content)
            return storage.Client.from_service_account_info(info)
        except Exception as e:
            print(f"❌ Error parsing GCS_KEY_JSON: {e}")
            return None
    elif os.path.exists(KEY_FILE_PATH):
        print(f"🔑 Authenticating using File: {KEY_FILE_PATH}")
        return storage.Client.from_service_account_json(KEY_FILE_PATH)
    else:
        print("❌ Error: No GCS Credentials found (File or Env)")
        return None

def upload_to_gcs(source_file_name):
    """อัปโหลดไฟล์ไป GCS และขอ Signed URL"""
    try:
        storage_client = get_gcs_client()
        if not storage_client:
            return None

        destination_blob_name = os.path.basename(source_file_name)
        print(f"☁️ Uploading {source_file_name} to GCS Bucket: {BUCKET_NAME}...")
        
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        
        # Upload (Timeout 300s)
        blob.upload_from_filename(source_file_name, timeout=300)

        # Generate Link (1 Hour Expiration - ปรับเวลาได้ตามต้องการ)
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=12), # เพิ่มเวลาให้ Link อยู่ได้นานขึ้น
            method="GET",
        )
        print(f"✅ Upload Success: {url}")
        return url
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        return None

# ---------------------------------------------------------
# 🎨 Helper Functions (Image & Font)
# ---------------------------------------------------------
def get_font(fontsize):
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    # Font สำรองสำหรับ Linux
    linux_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def download_image_from_url(url, filename):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            with open(filename, 'wb') as f: f.write(r.content)
            return True
    except: pass
    return False

def search_real_image(query, filename):
    print(f"🌍 Searching: {query[:20]}...")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results: return download_image_from_url(results[0]['image'], filename)
    except: pass
    return False

# ---------------------------------------------------------
# 🔊 Audio Function
# ---------------------------------------------------------
async def create_voice_safe(text, filename):
    try:
        # ใช้ Edge TTS เสียงภาษาไทย (Niwat) เร็วขึ้น 25%
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural", rate="+25%")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

# ---------------------------------------------------------
# 🎬 Video Components
# ---------------------------------------------------------
def create_watermark_clip(duration):
    try:
        # 1. โหลดไฟล์ Logo ของคุณ
        logo_path = "my_logo.png" 
        if not os.path.exists(logo_path):
            return None
            
        # 2. ปรับขนาด Logo (กว้าง 200 pixel)
        logo = (ImageClip(logo_path)
                .set_duration(duration)
                .resize(width=200)
                .set_opacity(0.9)
                .set_position(("right", "top"))) # วางมุมขวาบน
                
        return logo
    except Exception as e:
        print(f"Logo Error: {e}")
        return None

def create_text_clip(text, size=(720, 1280), duration=5):
    """สร้าง Subtitle โดยใช้ Pillow (เสถียรกว่า TextClip บน Linux)"""
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)

        font_size = 36
        font = get_font(font_size)
        
        # จัดการการตัดคำ (Word Wrap)
        limit_chars = 30
        lines = []
        temp = ""
        for char in text:
            if len(temp) < limit_chars: temp += char
            else: lines.append(temp); temp = char
        lines.append(temp)

        # คำนวณตำแหน่ง (วางไว้ด้านล่าง)
        line_height = font_size + 10
        total_height = len(lines) * line_height
        margin_bottom = 100
        start_y = size[1] - total_height - margin_bottom

        # วาด Background สีดำจางๆ
        padding = 15
        draw.rectangle([20, start_y - padding, size[0]-20, start_y + total_height + padding], fill=(0,0,0,160))

        # วาดตัวหนังสือ
        cur_y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) / 2
            
            # Stroke (ขอบตัวหนังสือ)
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            
            # Text (สีขาว)
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height

        return ImageClip(np.array(img)).set_duration(duration)
    except Exception as e:
        print(f"Subtitle Error: {e}")
        return None

# ---------------------------------------------------------
# 🎞️ Main Process Logic
# ---------------------------------------------------------
def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🎬 Starting Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        
        for i, scene in enumerate(scenes):
            gc.collect() # เคลียร์ RAM
            print(f"[{task_id}] Processing Scene {i+1}/{len(scenes)}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # 1. Prepare Image
            prompt = scene.get('image_url') or scene.get('imageUrl') or ''
            success = False
            
            # กรณีเป็น URL รูปภาพ
            if "http" in prompt and download_image_from_url(prompt, img_file): 
                success = True
            
            # กรณีต้อง Search (ถ้าโหลดไม่ผ่านหรือไม่ใช่ URL)
            if not success and prompt:
                search_real_image(prompt, img_file)
            
            # ถ้ายังไม่มีรูป ให้สร้างรูปดำ
            if not os.path.exists(img_file):
                Image.new('RGB', (720, 1280), (20,20,20)).save(img_file)

            # 2. Prepare Audio
            script_text = scene.get('script') or scene.get('caption') or "No content."
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(script_text, audio_file))

            # 3. Create Clip using MoviePy
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    # Audio
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration  # ไม่บวกเวลาเพิ่ม เพื่อให้เสียงต่อเนื่อง (Gapless)
                    
                    # Image (Pan/Zoom effect could be added here, currently static)
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    
                    # Subtitle
                    txt_clip = create_text_clip(script_text, duration=dur)
                    
                    # Logo
                    watermark = create_watermark_clip(dur)
                    
                    # Composite
                    layers = [img_clip]
                    if txt_clip: layers.append(txt_clip)
                    if watermark: layers.append(watermark)
                    
                    video = CompositeVideoClip(layers).set_audio(audio)
                    
                    # Write temp clip
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    valid_clips.append(clip_output)
                    
                    # Cleanup Memory
                    video.close(); audio.close(); img_clip.close()
                except Exception as e:
                    print(f"Scene Error: {e}")

        # --- Merge All Clips ---
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging {len(valid_clips)} clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            
            # Render Final Video
            final.write_videofile(output_filename, fps=15, bitrate="2000k", preset='ultrafast')
            
            # --- Upload to GCS ---
            url = upload_to_gcs(output_filename)
            
            # --- Callback to n8n ---
            if url:
                try:
                    payload = {
                        'id': task_id,        # ID เพื่อระบุแถวใน DB
                        'video_url': url,     # URL วิดีโอ
                        'status': 'success'
                    }
                    print(f"[{task_id}] 📞 Sending Callback to: {N8N_WEBHOOK_URL}")
                    requests.post(N8N_WEBHOOK_URL, json=payload, timeout=20)
                    print(f"[{task_id}] ✅ Callback sent successfully!")
                except Exception as e:
                    print(f"[{task_id}] ❌ Webhook/Callback Error: {e}")
            else:
                print(f"[{task_id}] ❌ Failed to get Upload URL")

            # Cleanup Final
            final.close()
            for c in clips: c.close()
        else:
            print(f"[{task_id}] ❌ No valid clips generated.")

    except Exception as e:
        print(f"[{task_id}] Critical Error: {e}")
        
    finally:
        # Cleanup Temp Files
        try:
            for f in os.listdir():
                if task_id in f and f.endswith(('.jpg', '.mp3', '.mp4')):
                    try: os.remove(f)
                    except: pass
            print(f"[{task_id}] 🧹 Cleanup done.")
        except: pass

# ---------------------------------------------------------
# 🚀 Flask API Routes
# ---------------------------------------------------------
@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    scenes = data.get('scenes', [])
    
    # ✅ รับ task_id จาก n8n (ถ้าไม่มีค่อยสร้างใหม่)
    task_id = data.get('task_id')
    if not task_id:
        task_id = str(uuid.uuid4())

    if not scenes: return jsonify({"error": "No scenes provided"}), 400
    
    print(f"🚀 Received Task: {task_id} with {len(scenes)} scenes")
    
    # Run in Background
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes))
    thread.start()
    
    return jsonify({"status": "processing", "task_id": task_id}), 202

@app.route('/', methods=['GET'])
def health_check():
    return "AI Video Engine is Running (Callback Enabled)!", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)