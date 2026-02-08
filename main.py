# ---------------------------------------------------------
# ✅ Mode: News Digest + Debug Upload (พูดมาก + อัปโหลด 3 เว็บ)
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
    font_names = ["tahoma.ttf", "arial.ttf", "NotoSansThai-Regular.ttf", "LeelawadeeUI.ttf"]
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

def search_real_image(query, filename):
    print(f"🌍 Searching Real Image for: {query[:30]}...")
    # ถ้า query เป็น URL ให้ข้ามไปเลย (ป้องกัน error)
    if "http" in query:
        print("⚠️ Query looks like a URL, skipping search.")
        return False
        
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results:
                image_url = results[0]['image']
                print(f"✅ Found Image: {image_url[:30]}...")
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    with open(filename, 'wb') as f: f.write(response.content)
                    with Image.open(filename) as img:
                        img.convert("RGB").resize((720, 1280)).save(filename)
                    return True
    except Exception as e:
        print(f"⚠️ Search Failed: {e}")
    return False

def generate_image_hf(prompt, filename):
    print(f"🎨 Generating AI Image: {prompt[:30]}...")
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
    url = scene.get('image_url', '')
    # ถ้า n8n ส่งมาเป็น URL ยาวๆ ให้ลองแกะ Prompt หรือใช้ Script แทน
    if "pollinations" in url or "http" in url:
        return scene['script'] # ใช้เนื้อหาข่าวค้นหาแทน URL
    if len(url) > 2: return url
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
        font_size = 45
        font = get_font(font_size)
        limit_chars = 18 
        
        lines = []
        temp_line = ""
        for char in text:
            if len(temp_line) < limit_chars: temp_line += char
            else:
                lines.append(temp_line)
                temp_line = char
        lines.append(temp_line)

        line_height = font_size + 15
        total_text_height = len(lines) * line_height
        bottom_margin = 250 
        start_y = size[1] - bottom_margin - total_text_height

        draw.rectangle([30, start_y - 15, size[0] - 30, start_y + total_text_height + 15], fill=(0, 0, 0, 180))

        cur_y = start_y
        for line in lines:
            try:
                left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
                x = (size[0] - (right - left)) / 2
            except: x = 50
            draw.text((x-2, cur_y), line, font=font, fill="black")
            draw.text((x, cur_y-2), line, font=font, fill="black")
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += line_height

        return ImageClip(np.array(img)).set_duration(duration)
    except:
        return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

def upload_to_host(filename):
    """🔥 ระบบอัปโหลด 3 ชั้น + Logs ละเอียดยิบ"""
    
    # 1. Catbox
    print(f"☁️ [1/3] Trying Catbox...")
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=60)
            if r.status_code == 200:
                print(f"✅ Upload Success (Catbox): {r.text}")
                return r.text
            else: print(f"⚠️ Catbox Error: {r.status_code}")
    except Exception as e: print(f"⚠️ Catbox Failed: {e}")

    # 2. Tmpfiles
    print(f"☁️ [2/3] Trying Tmpfiles...")
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60)
            if r.status_code == 200:
                url = r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Upload Success (Tmpfiles): {url}")
                return url
            else: print(f"⚠️ Tmpfiles Error: {r.status_code}")
    except Exception as e: print(f"⚠️ Tmpfiles Failed: {e}")
    
    # 3. File.io (ตัวสำรองสุดท้าย)
    print(f"☁️ [3/3] Trying File.io...")
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://file.io', files={'file': f}, timeout=60)
            if r.status_code == 200:
                url = r.json()['link']
                print(f"✅ Upload Success (File.io): {url}")
                return url
    except Exception as e: print(f"⚠️ File.io Failed: {e}")

    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Scene {i+1}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # Image Logic
            prompt = get_clean_prompt(scene)
            if not search_real_image(prompt, img_file):
                print("⚠️ Real image not found, using AI...")
                if not generate_image_hf(prompt, img_file):
                    Image.new('RGB', (720, 1280), color=(0, 0, 100)).save(img_file)

            # Audio Logic
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # Render
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5 
                    if dur < 5: dur = 5
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
                    video.write_videofile(clip_output, fps=15, codec='libx264', audio_codec='aac', preset='ultrafast', threads=2, logger=None)
                    
                    if os.path.exists(clip_output): valid_clips.append(clip_output)
                    video.close(); audio.close(); img_clip.close(); txt_clip.close()
                    del video, audio, img_clip, txt_clip
                    gc.collect()
                except Exception as e: print(f"❌ Error Scene {i}: {e}")

        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging Clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, preset='ultrafast')
            
            # ✅ Upload พร้อม Logs ละเอียด
            print(f"[{task_id}] 📤 Uploading Video...")
            video_url = upload_to_host(output_filename)
            
            if video_url:
                print(f"[{task_id}] 🚀 Sending Webhook to n8n...")
                try:
                    requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': video_url}, timeout=10)
                except Exception as e: print(f"❌ Webhook Failed: {e}")
            else:
                print(f"[{task_id}] ❌ ALL UPLOADS FAILED.")
            
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