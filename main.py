# ---------------------------------------------------------
# ✅ Mode: News Brief Pro (Fast Upload + Compressed Video)
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

# --- Helper Functions (เหมือนเดิม) ---

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
            if results:
                return download_image_from_url(results[0]['image'], filename)
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

async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

def create_watermark_clip(duration):
    try:
        size = (720, 1280)
        img = Image.new('RGBA', size, (0,0,0,0))
        draw = ImageDraw.Draw(img)
        text = "NEWS BRIEF"
        font = get_font(40)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = size[0] - w - 30
        y = 80
        draw.rectangle([x-10, y-5, x+w+10, y+h+5], fill=(200, 0, 0, 255)) 
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
        y = size[1] - 350 - h
        draw.rectangle([20, y-10, size[0]-20, y+h+20], fill=(0,0,0,160))
        cur_y = y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
            x = (size[0] - w) / 2
            draw.text((x-1, cur_y), line, font=font, fill="black")
            draw.text((x+1, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += 60
        return ImageClip(np.array(img)).set_duration(duration)
    except: return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

# ---------------------------------------------------------
# 🔥 อัปเกรดระบบอัปโหลด (ไวขึ้น + มี Timeout)
# ---------------------------------------------------------
def upload_to_host(filename):
    print(f"☁️ Uploading File Size: {os.path.getsize(filename) / (1024*1024):.2f} MB")

    # 1. Catbox (ดีสุด แต่บางทีช้า)
    print("🚀 Try 1: Catbox...")
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://catbox.moe/user/api.php', 
                              data={'reqtype': 'fileupload'}, 
                              files={'fileToUpload': f}, 
                              timeout=45) # ตัดจบถ้าเกิน 45 วิ
            if r.status_code == 200: return r.text
    except Exception as e: print(f"⚠️ Catbox Failed: {e}")

    # 2. Transfer.sh (ไวมาก เป็นตัวสำรองชั้นดี)
    print("🚀 Try 2: Transfer.sh (Fast Backup)...")
    try:
        with open(filename, 'rb') as f:
            # ใช้ curl style upload
            r = requests.put(f'https://transfer.sh/{os.path.basename(filename)}', data=f, timeout=45)
            if r.status_code == 200:
                return r.text.strip()
    except Exception as e: print(f"⚠️ Transfer.sh Failed: {e}")

    # 3. Tmpfiles (ตัวสุดท้าย)
    print("🚀 Try 3: Tmpfiles...")
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=45)
            if r.status_code == 200: 
                return r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    except: pass

    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🎬 Starting Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Scene {i+1}/{len(scenes)}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"
            
            # Image Logic
            prompt = scene.get('image_url', '')
            success = False
            if "http" in prompt:
                if download_image_from_url(prompt, img_file): success = True
            if not success:
                if not search_real_image(prompt, img_file):
                    if not generate_image_hf(prompt, img_file):
                        Image.new('RGB', (720, 1280), (0,0,50)).save(img_file)

            # Audio Logic
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # Render Clip
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = max(4, audio.duration + 0.5)
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    watermark = create_watermark_clip(dur)
                    
                    layers = [img_clip, txt_clip]
                    if watermark: layers.append(watermark)
                    
                    video = CompositeVideoClip(layers).set_audio(audio)
                    # ⚠️ เรนเดอร์แบบ Draft Quality (ไวขึ้น)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    valid_clips.append(clip_output)
                    video.close(); audio.close(); img_clip.close(); txt_clip.close()
                except Exception as e: print(f"❌ Error Scene {i}: {e}")

        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging & Compressing...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            
            # 🔥 บีบอัดไฟล์ (Bitrate 2000k) เพื่อให้ไฟล์เล็กและอัปโหลดไว
            final.write_videofile(output_filename, fps=15, bitrate="2000k", preset='ultrafast')
            
            url = upload_to_host(output_filename)
            if url:
                print(f"[{task_id}] ✅ DONE: {url}")
                requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': url})
            else:
                print(f"[{task_id}] ❌ Upload Failed")
            
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