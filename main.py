# ---------------------------------------------------------
# ✅ Mode: News Digest (Real Images + Safe Subtitles)
import sys
sys.stdout.reconfigure(line_buffering=True)
import os
# ---------------------------------------------------------

from flask import Flask, request, jsonify
import threading
import uuid
import time
import requests
from huggingface_hub import InferenceClient
from duckduckgo_search import DDGS # ✅ พระเอกคนใหม่ (หารูปจริง)
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio
import gc
from urllib.parse import unquote

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Webhook URL
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"
HF_TOKEN = os.environ.get("HF_TOKEN")

# --- Helper Functions ---

def get_font(fontsize):
    # หาฟอนต์ที่อ่านง่ายๆ สำหรับข่าว
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf", "LeelawadeeUI.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    
    linux_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", # มักจะมีตัวนี้
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def search_real_image(query, filename):
    """🔍 ค้นหารูปจริงจาก DuckDuckGo"""
    print(f"🌍 Searching Real Image for: {query}...")
    try:
        with DDGS() as ddgs:
            # ค้นหา 1 รูป
            results = list(ddgs.images(query, max_results=1))
            if results:
                image_url = results[0]['image']
                print(f"✅ Found Image: {image_url[:50]}...")
                
                # โหลดรูป
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    with open(filename, 'wb') as f: f.write(response.content)
                    # แปลงเป็น JPG มาตรฐาน
                    with Image.open(filename) as img:
                        img.convert("RGB").resize((720, 1280)).save(filename)
                    return True
    except Exception as e:
        print(f"⚠️ Search Failed: {e}")
    return False

def generate_image_hf(prompt, filename):
    """🎨 แผนสำรอง: ถ้าหารูปจริงไม่ได้ ให้ AI วาดแทน"""
    print(f"🎨 Generating Backup Image: {prompt[:30]}...")
    if not HF_TOKEN: return False
    
    models = ["black-forest-labs/FLUX.1-dev", "stabilityai/stable-diffusion-xl-base-1.0"]
    client = InferenceClient(token=HF_TOKEN)
    
    for model in models:
        try:
            image = client.text_to_image(prompt, model=model, height=1024, width=768)
            image = image.convert("RGB").resize((720, 1280))
            image.save(filename)
            return True
        except: time.sleep(1)
    return False

def get_clean_prompt(scene):
    # ดึง Keyword สำหรับค้นหารูป
    url = scene.get('image_url', '')
    # ถ้าเป็น Prompt ยาวๆ ให้ใช้เลย
    if len(url) > 2: return url
    # ถ้าไม่มี ให้ใช้ Script
    return scene['script']

async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

def create_text_clip(text, size=(720, 1280), duration=5):
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        
        # 📏 Config ตัวอักษร
        font_size = 45 # ใหญ่ขึ้นนิดนึงให้อ่านง่าย
        font = get_font(font_size)
        limit_chars = 18 # จำนวนตัวอักษรต่อบรรทัด (ข่าวอ่านไว)
        
        # ✂️ ตัดคำ (Word Wrap)
        lines = []
        temp_line = ""
        for char in text: # ตัดทีละตัวอักษร (แก้ปัญหาภาษาไทย)
            if len(temp_line) < limit_chars:
                temp_line += char
            else:
                lines.append(temp_line)
                temp_line = char
        lines.append(temp_line)

        # 📐 คำนวณตำแหน่ง (ดันขึ้นจากด้านล่าง)
        line_height = font_size + 15
        total_text_height = len(lines) * line_height
        
        # Position: วางไว้ด้านล่าง (Bottom Anchor)
        # ลบ 250px จากขอบล่าง (เผื่อพื้นที่ UI TikTok)
        bottom_margin = 250 
        start_y = size[1] - bottom_margin - total_text_height

        # ⬛ วาดกล่องดำรองหลัง (Background Box)
        box_padding = 15
        draw.rectangle(
            [30, start_y - box_padding, size[0] - 30, start_y + total_text_height + box_padding], 
            fill=(0, 0, 0, 180) # ดำเข้มขึ้นนิดนึง
        )

        # ✍️ วาดตัวหนังสือ
        cur_y = start_y
        for line in lines:
            try:
                # จัดกึ่งกลาง
                left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
                text_width = right - left
                x = (size[0] - text_width) / 2
            except: x = 50
            
            # ขอบตัวหนังสือสีดำ (Stroke) ให้อ่านชัดขึ้น
            draw.text((x-2, cur_y), line, font=font, fill="black")
            draw.text((x+2, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y-2), line, font=font, fill="black")
            draw.text((x, cur_y+2), line, font=font, fill="black")
            
            # ตัวหนังสือสีขาว
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height

        return ImageClip(np.array(img)).set_duration(duration)
    except Exception as e:
        print(f"⚠️ Text Error: {e}")
        return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

def upload_to_host(filename):
    # Upload Logic (Catbox เป็นหลัก เพราะเก็บได้นานกว่า)
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=120)
            if r.status_code == 200: return r.text
    except: pass
    
    # Backup: tmpfiles
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60)
            if r.status_code == 200:
                return r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    except: pass
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting News Video Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Scene {i+1}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # 1. Image Search (Real -> AI)
            search_query = get_clean_prompt(scene)
            if not search_real_image(search_query, img_file):
                print("⚠️ Real image not found, using AI...")
                if not generate_image_hf(search_query, img_file):
                    # ถ้าพังหมด ให้สร้างภาพสีพื้น
                    Image.new('RGB', (720, 1280), color=(0, 0, 100)).save(img_file)

            # 2. Audio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # 3. Render
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5 
                    if dur < 5: dur = 5 # ขั้นต่ำ 5 วินาที
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    
                    video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    if os.path.exists(clip_output): valid_clips.append(clip_output)
                    
                    video.close(); audio.close(); img_clip.close(); txt_clip.close()
                    del video, audio, img_clip, txt_clip
                    gc.collect()
                except Exception as e: print(f"❌ Error Scene {i}: {e}")

        # 4. Merge
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, preset='ultrafast')
            
            video_url = upload_to_host(output_filename)
            if video_url:
                print(f"[{task_id}] ✅ Success: {video_url}")
                requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': video_url})
            
            final.close()
            for c in clips: c.close()

    except Exception as e: print(f"[{task_id}] Error: {e}")
    finally:
        try:
            for f in os.listdir():
                if task_id in f: os.remove(f)
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