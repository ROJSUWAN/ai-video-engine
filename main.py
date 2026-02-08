# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (Auto-Fix Keys: script/caption)
# ---------------------------------------------------------
import sys
# บังคับให้ Python พ่น Log ออกมาทันที
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
from huggingface_hub import InferenceClient
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
# เปลี่ยน URL Webhook ของคุณตรงนี้ (ถ้ามีการเปลี่ยนแปลง)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

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
    # 1. ลองดูว่ามี Environment Variable ที่เก็บ JSON ไว้ไหม (สำหรับ Railway)
    gcs_json_content = os.environ.get("GCS_KEY_JSON")
    if gcs_json_content:
        try:
            print("🔑 Authenticating using Environment Variable...")
            info = json.loads(gcs_json_content)
            return storage.Client.from_service_account_info(info)
        except Exception as e:
            print(f"❌ Error parsing GCS_KEY_JSON: {e}")
            return None
            
    # 2. ถ้าไม่มี Env ให้ลองหาไฟล์ (สำหรับ Local Computer)
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

        # Generate Link (1 Hour Expiration)
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=60),
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
    linux_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def create_fitted_image(img_path):
    try:
        target_size = (720, 1280)
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            bg = img.resize(target_size)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
            img.thumbnail((720, 1280))
            x = (target_size[0] - img.width) // 2
            y = (target_size[1] - img.height) // 2
            bg.paste(img, (x, y))
            bg.save(img_path)
            return True
    except: return False

def download_image_from_url(url, filename):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            with open(filename, 'wb') as f: f.write(r.content)
            create_fitted_image(filename)
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

def generate_image_hf(prompt, filename):
    print(f"🎨 Generating AI: {prompt[:20]}...")
    if not HF_TOKEN: return False
    client = InferenceClient(token=HF_TOKEN)
    try:
        image = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-dev", height=1024, width=768)
        image = image.convert("RGB").resize((720, 1280))
        image.save(filename)
        return True
    except: return False

# ---------------------------------------------------------
# 🔊 Audio Function
# ---------------------------------------------------------
async def create_voice_safe(text, filename):
    try:
        # ใช้ Edge TTS เสียงภาษาไทย (Niwat)
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural", rate="+25%")
        await communicate.save(filename)
    except:
        # สำรองใช้ gTTS
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

# ---------------------------------------------------------
# 🎬 Video Components
# ---------------------------------------------------------
def create_watermark_clip(duration):
    try:
        size = (720, 1280)
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        
        # ตั้งค่า Font และข้อความตามรูป Logo ใหม่
        font_big = get_font(50)   # สำหรับคำว่า THE BRIEF
        font_small = get_font(20)  # สำหรับคำว่า NEWS IN MINUTES
        
        # วาดแถบสีขาว/ดำ หรือโปร่งใสตามดีไซน์รูปที่แนบมา
        # (ในที่นี้แนะนำให้วาด Text ลงไปตรงๆ เพื่อความง่าย)
        draw.text((500, 50), "THE", font=font_small, fill="white")
        draw.text((500, 75), "BRIEF", font=font_big, fill="white")
        draw.text((500, 130), "NEWS IN MINUTES", font=font_small, fill="red")
        
        return ImageClip(np.array(img)).set_duration(duration)
    except: return None

def create_text_clip(text, size=(720, 1280), duration=5):
    """สร้าง Subtitle แบบใหม่: ตัวเล็ก + ชิดล่าง"""
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)

        font_size = 32
        font = get_font(font_size)
        limit_chars = 35
        lines = []
        temp = ""
        for char in text:
            if len(temp) < limit_chars: temp += char
            else: lines.append(temp); temp = char
        lines.append(temp)

        line_height = font_size + 10
        total_height = len(lines) * line_height
        margin_bottom = 50
        start_y = size[1] - total_height - margin_bottom

        padding = 10
        draw.rectangle([20, start_y - padding, size[0]-20, start_y + total_height + padding], fill=(0,0,0,180))

        cur_y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) / 2
            
            # Stroke + Text
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height

        return ImageClip(np.array(img)).set_duration(duration)
    except Exception as e:
        print(f"Subtitle Error: {e}")
        return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

# ---------------------------------------------------------
# 🎞️ Main Process (หัวใจสำคัญ - แก้ไขแล้ว)
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

            # ✅ 1. แก้ไข Image Key (รองรับ image_url หรือ imageUrl)
            prompt = scene.get('image_url') or scene.get('imageUrl') or ''
            
            success = False
            if "http" in prompt and download_image_from_url(prompt, img_file): success = True
            if not success and not search_real_image(prompt, img_file):
                if not generate_image_hf(prompt, img_file):
                    Image.new('RGB', (720, 1280), (0,0,50)).save(img_file)

            # ✅ 2. แก้ไข Script Key (รองรับ script หรือ caption)
            # ถ้าไม่มีทั้งคู่ ให้ใส่ข้อความว่างๆ เพื่อกัน Error
            script_text = scene.get('script') or scene.get('caption') or "No content available."

            # สร้างเสียง
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(script_text, audio_file))

            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = max(4, audio.duration +0.2)
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    # ใช้ script_text ที่ดึงมาอย่างถูกต้อง
                    txt_clip = create_text_clip(script_text, duration=dur)
                    watermark = create_watermark_clip(dur)
                    
                    layers = [img_clip, txt_clip]
                    if watermark: layers.append(watermark)
                    
                    video = CompositeVideoClip(layers).set_audio(audio)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    valid_clips.append(clip_output)
                    
                    video.close(); audio.close(); img_clip.close(); txt_clip.close()
                except Exception as e: print(f"Scene Error: {e}")

        # --- รวมคลิปและอัปโหลด ---
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging {len(valid_clips)} clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, bitrate="2000k", preset='ultrafast')
            
            # ✅ Upload
            url = upload_to_gcs(output_filename)
            
            if url:
                try:
                    requests.post(N8N_WEBHOOK_URL, json={
                        'task_id': task_id, 
                        'status': 'success', 
                        'video_url': url
                    }, timeout=20)
                    print(f"[{task_id}] ✅ Webhook sent successfully!")
                except Exception as e:
                    print(f"[{task_id}] ❌ Webhook Error: {e}")
            else:
                print(f"[{task_id}] ❌ Failed to get Upload URL")

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
                    os.remove(f)
            print(f"[{task_id}] 🧹 Cleanup done.")
        except: pass

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    scenes = data.get('scenes', [])
    if not scenes: return jsonify({"error": "No scenes provided"}), 400
    
    task_id = str(uuid.uuid4())
    print(f"🚀 Received Task: {task_id}")
    
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes))
    thread.start()
    
    return jsonify({"status": "processing", "task_id": task_id}), 202

@app.route('/', methods=['GET'])
def health_check():
    return "AI Video Engine is Running (Safe Mode)!", 200

if __name__ == '__main__':
    # รองรับ Port จาก Railway
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)