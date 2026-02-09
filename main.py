# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (Final Fix: Master Image Backup Logic)
# ---------------------------------------------------------
import sys
# บังคับให้ Python พ่น Log ออกมาทันที
sys.stdout.reconfigure(line_buffering=True)

import os
import shutil
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
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook/video-completed"

# Environment Variables
HF_TOKEN = os.environ.get("HF_TOKEN")

# ⚙️ Google Cloud Storage Config
BUCKET_NAME = "n8n-video-storage-0123"
KEY_FILE_PATH = "gcs_key.json"

# ---------------------------------------------------------
# ☁️ Upload Function
# ---------------------------------------------------------
def get_gcs_client():
    gcs_json_content = os.environ.get("GCS_KEY_JSON")
    if gcs_json_content:
        try:
            info = json.loads(gcs_json_content)
            return storage.Client.from_service_account_info(info)
        except: return None
    elif os.path.exists(KEY_FILE_PATH):
        return storage.Client.from_service_account_json(KEY_FILE_PATH)
    return None

def upload_to_gcs(source_file_name):
    try:
        storage_client = get_gcs_client()
        if not storage_client: return None
        destination_blob_name = os.path.basename(source_file_name)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name, timeout=300)
        url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(hours=12), method="GET")
        print(f"✅ Upload Success: {url}")
        return url
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        return None

# ---------------------------------------------------------
# 🎨 Helper Functions (Image)
# ---------------------------------------------------------
def smart_resize_image(img_path):
    try:
        target_size = (720, 1280)
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            if img.size == target_size: return True
            
            bg = img.copy()
            bg_ratio = target_size[0] / target_size[1]
            img_ratio = img.width / img.height
            
            if img_ratio > bg_ratio:
                resize_height = target_size[1]
                resize_width = int(resize_height * img_ratio)
            else:
                resize_width = target_size[0]
                resize_height = int(resize_width / img_ratio)
                
            bg = bg.resize((resize_width, resize_height), Image.Resampling.LANCZOS)
            left = (bg.width - target_size[0]) // 2
            top = (bg.height - target_size[1]) // 2
            bg = bg.crop((left, top, left + target_size[0], top + target_size[1]))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
            
            img.thumbnail((720, 1280), Image.Resampling.LANCZOS)
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
            smart_resize_image(filename)
            return True
    except: pass
    return False

def search_real_image(query, filename):
    # ดักคำมั่ว
    if not query or "SELECT" in query or "INSERT" in query or "GALLERY" in query or len(query) < 3:
        return False
        
    print(f"🌍 Searching: {query[:30]}...")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results: return download_image_from_url(results[0]['image'], filename)
    except: pass
    return False

# ---------------------------------------------------------
# 🔊 Audio & Components
# ---------------------------------------------------------
async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural", rate="+25%")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

def get_font(fontsize):
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    linux_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def create_watermark_clip(duration):
    try:
        logo_path = "my_logo.png" 
        if not os.path.exists(logo_path): return None
        return (ImageClip(logo_path).set_duration(duration)
                .resize(width=200).set_opacity(0.9).set_position(("right", "top")))
    except: return None

def create_text_clip(text, size=(720, 1280), duration=5):
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        font_size = 28; font = get_font(font_size)
        
        # ตัดคำให้เหมาะสม
        limit_chars = 40; lines = []; temp = ""
        for char in text:
            if len(temp) < limit_chars: temp += char
            else: lines.append(temp); temp = char
        lines.append(temp)
        
        line_height = font_size + 10; total_height = len(lines) * line_height
        
        # ---------------------------------------------------------
        # ✅ แก้ไขตำแหน่ง: เปลี่ยนจากด้านล่างเป็นด้านบน (Margin 200)
        # ---------------------------------------------------------
        margin_top = 130 
        start_y = margin_top 
        # ---------------------------------------------------------
        
        # วาดพื้นหลังสีดำโปร่งแสง (Rectangle) หลังข้อความ
        draw.rectangle([20, start_y - 15, size[0]-20, start_y + total_height + 15], fill=(0,0,0,160))
        
        cur_y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) / 2
            # วาดเงา/ขอบสีดำ และตัวอักษรสีขาว
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height
            
        return ImageClip(np.array(img)).set_duration(duration)
    except: return None

# ---------------------------------------------------------
# 🎞️ Main Process Logic (Fixed: Master Image Sync)
# ---------------------------------------------------------
def process_video_background(task_id, scenes, topic):
    print(f"[{task_id}] 🎬 Starting Process (Topic: {topic})...")
    output_filename = f"video_{task_id}.mp4"
    
    # ---------------------------------------------------------
    # ⭐ STEP 1: พยายามหารูปจากหัวข้อข่าว (Topic)
    # ---------------------------------------------------------
    master_image_path = f"master_{task_id}.jpg"
    is_master_valid = False # ตัวแปรเช็คว่ารูป Master ใช้ได้จริงไหม
    
    print(f"[{task_id}] 🖼️ Fetching Master Image for topic: {topic}")
    if search_real_image(topic, master_image_path):
        is_master_valid = True
        smart_resize_image(master_image_path)
        print(f"[{task_id}] ✅ Master Image Set from Topic!")
    else:
        # ถ้าหาไม่เจอ ให้สร้างภาพดำไว้ก่อน (แต่ตั้ง Flag ว่า False)
        print(f"[{task_id}] ⚠️ Topic search failed. Creating placeholder.")
        Image.new('RGB', (720, 1280), (20,20,20)).save(master_image_path)
        is_master_valid = False

    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Processing Scene {i+1}/{len(scenes)}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # ---------------------------------------------------------
            # ⭐ STEP 2: Logic เลือกรูป (แก้ไขแล้ว)
            # ---------------------------------------------------------
            prompt = scene.get('image_url') or scene.get('imageUrl') or ''
            used_specific_image = False
            
            # 2.1 หารูปเฉพาะ Scene
            if prompt and "SELECT" not in prompt and "GALLERY" not in prompt and len(prompt) > 5:
                if "http" in prompt:
                    if download_image_from_url(prompt, img_file): used_specific_image = True
                elif not used_specific_image:
                    if search_real_image(prompt, img_file): used_specific_image = True

            # 2.2 ตัดสินใจว่าจะใช้รูปไหน
            if used_specific_image:
                # ถ้าเจอรูปเฉพาะ ให้ใช้รูปนี้
                smart_resize_image(img_file)
                
                # 🔥 KEY FIX: ถ้า Master Image ยังเป็นภาพดำ (หาไม่เจอ) ให้เอารูป Scene นี้ไปเป็น Master ทันที!
                # (เพื่อให้ Scene ถัดๆ ไป มีรูปใช้ ไม่ดำ)
                if not is_master_valid:
                    print(f"[{task_id}] 🔄 Updating Master Image using Scene {i+1}...")
                    shutil.copy(img_file, master_image_path)
                    is_master_valid = True
            else:
                # ถ้าไม่มีรูปเฉพาะ -> ใช้ Master Image (รูปหัวข้อ หรือรูปจาก Scene ก่อนหน้า)
                print(f"[{task_id}] 🔄 Using Master Image.")
                shutil.copy(master_image_path, img_file)

            # ---------------------------------------------------------
            # สร้างเสียงและคลิป
            # ---------------------------------------------------------
            script_text = scene.get('script') or scene.get('caption') or "No content."
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(script_text, audio_file))

            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration
                    
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
                except Exception as e: print(f"Scene Error: {e}")

        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging {len(valid_clips)} clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, bitrate="2000k", preset='ultrafast')
            
            url = upload_to_gcs(output_filename)
            if url:
                try:
                    payload = {'id': task_id, 'video_url': url, 'status': 'success'}
                    requests.post(N8N_WEBHOOK_URL, json=payload, timeout=20)
                    print(f"[{task_id}] ✅ Callback sent!")
                except: pass
            
            final.close()
            for c in clips: c.close()

    except Exception as e: print(f"Error: {e}")
    finally:
        try:
            for f in os.listdir():
                if task_id in f and f.endswith(('.jpg', '.mp3', '.mp4')):
                    try: os.remove(f)
                    except: pass
        except: pass

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    scenes = data.get('scenes', [])
    task_id = data.get('task_id') or str(uuid.uuid4())
    topic = data.get('topic') or ""
    
    if not scenes: return jsonify({"error": "No scenes provided"}), 400
    
    print(f"🚀 Received Task: {task_id} | Topic: {topic}")
    thread = threading.Thread(target=process_video_background, args=(task_id, scenes, topic))
    thread.start()
    
    return jsonify({"status": "processing", "task_id": task_id}), 202

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)