# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (30-45s + Watermark + Credit)
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
from duckduckgo_search import DDGS
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio
import gc

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Config
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"
HF_TOKEN = os.environ.get("HF_TOKEN")

# --- Helper Functions ---

def get_font(fontsize):
    # หาฟอนต์ภาษาไทย
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf", "LeelawadeeUI.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    # Linux Fallback
    linux_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for path in linux_paths:
        if os.path.exists(path): return ImageFont.truetype(path, fontsize)
    return ImageFont.load_default()

def create_fitted_image(img_path):
    """✨ ทำภาพพื้นหลังเบลอ (Blurred Background) ให้ดูแพง"""
    try:
        target_size = (720, 1280)
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            
            # 1. สร้างพื้นหลังเบลอจากรูปเดิม (จะได้โทนสีเดียวกัน ไม่ดำมืด)
            bg = img.resize(target_size) 
            bg = bg.filter(ImageFilter.GaussianBlur(radius=40)) # เบลอให้นวลๆ
            
            # 2. ปรับแสงพื้นหลังให้มืดลงนิดนึง (เพื่อให้รูปหน้าเด่นขึ้น)
            # (ถ้าชอบสว่างๆ ลบบรรทัดนี้ได้ แต่ใส่ไว้จะทำให้อ่านซับง่ายขึ้น)
            # overlay = Image.new('RGBA', target_size, (0,0,0,50))
            # bg.paste(overlay, (0,0), overlay)

            # 3. วางรูปจริงตรงกลาง (Fit Width)
            img.thumbnail((720, 1280)) 
            x = (target_size[0] - img.width) // 2
            y = (target_size[1] - img.height) // 2
            bg.paste(img, (x, y))
            
            bg.save(img_path)
            return True
    except Exception as e:
        print(f"⚠️ Fit Image Error: {e}")
        return False

def download_image_from_url(url, filename):
    print(f"⬇️ Downloading Cover: {url[:50]}...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            with open(filename, 'wb') as f: f.write(response.content)
            create_fitted_image(filename) # เรียกใช้ฟังก์ชันทำภาพเบลอ
            return True
    except: pass
    return False

def search_real_image(query, filename):
    print(f"🌍 Searching Image: {query[:30]}...")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results:
                image_url = results[0]['image']
                return download_image_from_url(image_url, filename)
    except: pass
    return False

def generate_image_hf(prompt, filename):
    print(f"🎨 Generating AI Image: {prompt[:30]}...")
    if not HF_TOKEN: return False
    client = InferenceClient(token=HF_TOKEN)
    try:
        image = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-dev", height=1024, width=768)
        image = image.convert("RGB").resize((720, 1280))
        image.save(filename)
        return True
    except: return False

async def create_voice_safe(text, filename):
    try:
        # ใช้เสียง Niwat (เสียงผู้ชายยอดฮิต ดูเป็นทางการ)
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

def create_watermark_clip(duration):
    """🏷️ สร้างป้ายชื่อช่อง NEWS BRIEF มุมขวาบน"""
    try:
        size = (720, 1280)
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        
        text = "NEWS BRIEF"
        font = get_font(40) # ขนาดตัวอักษร
        
        # คำนวณตำแหน่ง (ขวาบน)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        
        padding = 30
        x = size[0] - w - padding
        y = padding + 50 # ลงมาจากขอบบนหน่อยนึง (เผื่อติด UI TikTok)

        # วาดพื้นหลังป้ายชื่อ (สีแดงสด เหมือนข่าว)
        bg_bbox = [x - 10, y - 5, x + w + 10, y + h + 5]
        draw.rectangle(bg_bbox, fill=(200, 0, 0, 255)) 
        
        # วาดตัวหนังสือสีขาว
        draw.text((x, y), text, font=font, fill="white")
        
        return ImageClip(np.array(img)).set_duration(duration)
    except: return None

def create_text_clip(text, size=(720, 1280), duration=5):
    try:
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        font = get_font(45)
        
        limit_chars = 20
        lines = []
        temp = ""
        for char in text:
            if len(temp) < limit_chars: temp += char
            else: lines.append(temp); temp = char
        lines.append(temp)

        h = len(lines) * 60
        y = size[1] - 350 - h # ดันขึ้นมาจากข้างล่าง
        
        # พื้นหลังSubtitle (สีดำโปร่งแสง)
        draw.rectangle([20, y-10, size[0]-20, y+h+20], fill=(0,0,0,160))

        cur_y = y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
            x = (size[0] - w) / 2
            # ตัวหนังสือขาว ขอบดำ
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += 60
            
        return ImageClip(np.array(img)).set_duration(duration)
    except: return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

def upload_to_host(filename):
    print(f"☁️ Uploading...")
    # 1. Catbox
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=60)
            if r.status_code == 200: return r.text
    except: pass
    # 2. Tmpfiles (Backup)
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60)
            if r.status_code == 200: return r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    except: pass
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting News Brief Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Scene {i+1}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"
            
            # Logic หารูป: ถ้าเป็น Link -> โหลด, ถ้าเป็นคำ -> ค้นหา
            prompt = scene.get('image_url', '')
            success = False
            
            if "http" in prompt:
                if download_image_from_url(prompt, img_file): success = True
            
            if not success:
                # ลองค้นหารูปจริงก่อน
                if not search_real_image(prompt, img_file):
                    # ถ้าไม่เจอ ใช้ AI วาด
                    if not generate_image_hf(prompt, img_file):
                         # ถ้าพังหมด สร้างสีพื้น
                        Image.new('RGB', (720, 1280), (0,0,50)).save(img_file)

            # สร้างเสียง
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # รวมร่าง Clip
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = max(4, audio.duration + 0.5) # ขั้นต่ำ 4 วิ
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    watermark = create_watermark_clip(duration=dur) # ✅ สร้างโลโก้ช่อง
                    
                    # รวมทุกอย่างเข้าด้วยกัน (Layer)
                    layers = [img_clip, txt_clip]
                    if watermark: layers.append(watermark) # แปะโลโก้ทับบนสุด
                    
                    video = CompositeVideoClip(layers).set_audio(audio)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    valid_clips.append(clip_output)
                    video.close(); audio.close(); img_clip.close(); txt_clip.close()
                except Exception as e: print(f"Error render scene {i}: {e}")

        # รวมทุกฉากเป็นวิดีโอเดียว
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging Final Video...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, preset='ultrafast')
            
            url = upload_to_host(output_filename)
            if url:
                print(f"[{task_id}] ✅ DONE: {url}")
                requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': url})
            
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