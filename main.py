# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (Final Fix: Smart Resize + Blur Background)
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
# ✅ URL Webhook (Production)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook/video-completed"

# Environment Variables
HF_TOKEN = os.environ.get("HF_TOKEN")

# ⚙️ Google Cloud Storage Config
BUCKET_NAME = "n8n-video-storage-0123"
KEY_FILE_PATH = "gcs_key.json"

# ---------------------------------------------------------
# ☁️ Upload Function (Secure Version)
# ---------------------------------------------------------
def get_gcs_client():
    """สร้าง Client โดยดูว่ามาจาก File หรือ Env Variable"""
    gcs_json_content = os.environ.get("GCS_KEY_JSON")
    if gcs_json_content:
        try:
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

        # Generate Link (12 Hours Expiration)
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=12),
            method="GET",
        )
        print(f"✅ Upload Success: {url}")
        return url
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        return None

# ---------------------------------------------------------
# 🎨 Helper Functions (Image & Font) - ⭐ จุดแก้ไขสำคัญ
# ---------------------------------------------------------
def smart_resize_image(img_path):
    """
    ฟังก์ชันสำคัญ: ปรับขนาดภาพให้เป็น 720x1280 (9:16)
    โดยไม่ยืดภาพ (No Stretch) แต่ใช้เทคนิค Blur Background แทน
    """
    try:
        target_size = (720, 1280)
        
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            
            # ถ้าขนาดเท่ากันเป๊ะอยู่แล้ว ให้ข้ามไป
            if img.size == target_size:
                return True

            # 1. สร้างพื้นหลังเบลอ (Background)
            bg = img.copy()
            # คำนวณสัดส่วนเพื่อขยายให้เต็มจอ
            bg_ratio = target_size[0] / target_size[1]
            img_ratio = img.width / img.height
            
            if img_ratio > bg_ratio: # ภาพต้นฉบับกว้างกว่า (แนวนอน)
                resize_height = target_size[1]
                resize_width = int(resize_height * img_ratio)
            else: # ภาพต้นฉบับสูงกว่า
                resize_width = target_size[0]
                resize_height = int(resize_width / img_ratio)
                
            bg = bg.resize((resize_width, resize_height), Image.Resampling.LANCZOS)
            
            # Crop ตรงกลางให้ได้ขนาด 720x1280
            left = (bg.width - target_size[0]) // 2
            top = (bg.height - target_size[1]) // 2
            bg = bg.crop((left, top, left + target_size[0], top + target_size[1]))
            
            # ใส่ Blur
            bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
            
            # 2. ย่อภาพจริงให้พอดีกรอบ (Thumbnail)
            img.thumbnail((720, 1280), Image.Resampling.LANCZOS)
            
            # 3. แปะภาพจริงลงตรงกลางพื้นหลัง
            x = (target_size[0] - img.width) // 2
            y = (target_size[1] - img.height) // 2
            bg.paste(img, (x, y))
            
            # บันทึกทับไฟล์เดิม
            bg.save(img_path)
            return True
    except Exception as e:
        print(f"Resize Error: {e}")
        return False

def get_font(fontsize):
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
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
            # ✅ เรียกใช้ Smart Resize ทันทีเมื่อโหลดเสร็จ
            smart_resize_image(filename)
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
        logo_path = "my_logo.png" 
        if not os.path.exists(logo_path):
            return None
        return (ImageClip(logo_path)
                .set_duration(duration)
                .resize(width=200)
                .set_opacity(0.9)
                .set_position(("right", "top")))
    except: return None

def create_text_clip(text, size=(720, 1280), duration=5):
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        font_size = 36
        font = get_font(font_size)
        limit_chars = 30
        lines = []
        temp = ""
        for char in text:
            if len(temp) < limit_chars: temp += char
            else: lines.append(temp); temp = char
        lines.append(temp)

        line_height = font_size + 10
        total_height = len(lines) * line_height
        margin_bottom = 100
        start_y = size[1] - total_height - margin_bottom
        
        padding = 15
        draw.rectangle([20, start_y - padding, size[0]-20, start_y + total_height + padding], fill=(0,0,0,160))
        
        cur_y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) / 2
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height
            
        return ImageClip(np.array(img)).set_duration(duration)
    except: return None

# ---------------------------------------------------------
# 🎞️ Main Process Logic
# ---------------------------------------------------------
def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🎬 Starting Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Processing Scene {i+1}/{len(scenes)}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # 1. Prepare Image
            prompt = scene.get('image_url') or scene.get('imageUrl') or ''
            success = False
            
            if "http" in prompt and download_image_from_url(prompt, img_file): 
                success = True
            
            if not success and prompt:
                search_real_image(prompt, img_file)
            
            # ถ้าไม่มีรูป ให้สร้างรูปดำ แล้วปรับขนาด
            if not os.path.exists(img_file):
                Image.new('RGB', (720, 1280), (20,20,20)).save(img_file)
            
            # ⭐ Double Check: เรียกใช้ Smart Resize อีกครั้งเพื่อความชัวร์
            smart_resize_image(img_file)

            # 2. Prepare Audio
            script_text = scene.get('script') or scene.get('caption') or "No content."
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(script_text, audio_file))

            # 3. Create Clip
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration
                    
                    # ✅ โหลดภาพมาใช้เลย ไม่ต้อง .resize((720, 1280)) อีก เพราะไฟล์ถูกแก้มาแล้ว
                    img_clip = ImageClip(img_file).set_duration(dur)
                    
                    txt_clip = create_text_clip(script_text, duration=dur)
                    watermark = create_watermark_clip(dur)
                    
                    layers = [img_clip]
                    if txt_clip: layers.append(txt_clip)
                    if watermark: layers.append(watermark)
                    
                    video = CompositeVideoClip(layers).set_audio(audio)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    valid_clips.append(clip_output)
                    
                    video.close(); audio.close(); img_clip.close()
                except Exception as e:
                    print(f"Scene Error: {e}")

        # --- Merge All Clips ---
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging {len(valid_clips)} clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            
            final.write_videofile(output_filename, fps=15, bitrate="2000k", preset='ultrafast')
            
            url = upload_to_gcs(output_filename)
            
            if url:
                try:
                    payload = {
                        'id': task_id,
                        'video_url': url,
                        'status': 'success'
                    }
                    requests.post(N8N_WEBHOOK_URL, json=payload, timeout=20)
                    print(f"[{task_id}] ✅ Callback sent successfully!")
                except Exception as e:
                    print(f"[{task_id}] ❌ Webhook Error: {e}")
            
            final.close()
            for c in clips: c.close()
        else:
            print(f"[{task_id}] ❌ No valid clips generated.")

    except Exception as e:
        print(f"[{task_id}] Critical Error: {e}")
    finally:
        try:
            for f in os.listdir():
                if task_id in f and f.endswith(('.jpg', '.mp3', '.mp4')):
                    try: os.remove(f)
                    except: pass
            print(f"[{task_id}] 🧹 Cleanup done.")
        except: pass

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    scenes = data.get('scenes', [])
    task_id = data.get('task_id')
    if not task_id: task_id = str(uuid.uuid4())

    if not scenes: return jsonify({"error": "No scenes provided"}), 400
    
    print(f"🚀 Received Task: {task_id} with {len(scenes)} scenes")
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes))
    thread.start()
    
    return jsonify({"status": "processing", "task_id": task_id}), 202

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)