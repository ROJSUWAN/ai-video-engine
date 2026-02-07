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
from huggingface_hub import InferenceClient
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio
import gc
import random
from urllib.parse import unquote

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Webhook URL
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# 🔑 Token ของคุณ
HF_TOKEN = "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"

# --- Helper Functions ---

def get_font(fontsize):
    try: return ImageFont.truetype("arial.ttf", fontsize)
    except: return ImageFont.load_default()

def create_placeholder_image(filename):
    img = Image.new('RGB', (720, 1280), color=(50, 50, 50))
    img.save(filename)

def generate_image_hf(prompt, filename):
    print(f"🎨 Generating Image: {prompt[:30]}...")
    models = ["black-forest-labs/FLUX.1-dev", "stabilityai/stable-diffusion-xl-base-1.0"]
    client = InferenceClient(token=HF_TOKEN)
    
    for model in models:
        try:
            image = client.text_to_image(prompt, model=model, height=1024, width=768)
            image = image.convert("RGB").resize((720, 1280))
            image.save(filename)
            print(f"✅ Image Success ({model})")
            return True
        except Exception as e:
            print(f"⚠️ {model} error: {e}")
            time.sleep(1)
    return False

def get_clean_prompt(scene):
    url = scene.get('image_url', '')
    if "pollinations" in url and "/prompt/" in url:
        try: return unquote(url.split("/prompt/")[1].split("?")[0])
        except: pass
    if len(url) > 10 and not url.startswith("http"): return url
    return f"High quality realistic photo of {scene['script']}, cinematic lighting, 8k"

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
        font = get_font(50)
        
        lines = []
        temp_line = ""
        for word in text.split(' '):
            if len(temp_line + word) < 20: temp_line += word + " "
            else:
                lines.append(temp_line)
                temp_line = word + " "
        lines.append(temp_line)

        text_height = len(lines) * 70
        start_y = size[1] - 350
        draw.rectangle([40, start_y - 20, size[0] - 40, start_y + text_height + 20], fill=(0, 0, 0, 160))

        cur_y = start_y
        for line in lines:
            try:
                left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
                x = (size[0] - (right - left)) / 2
            except: x = 60
            draw.text((x, cur_y), line, font=font, fill="white")
            cur_y += 70

        return ImageClip(np.array(img)).set_duration(duration)
    except:
        return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

def upload_to_host(filename):
    """🔥 ระบบอัปโหลดแบบ Hybrid (ลอง 2 เว็บ)"""
    
    # วิธีที่ 1: tmpfiles.org
    try:
        print(f"☁️ Trying upload to tmpfiles.org...")
        with open(filename, 'rb') as f:
            # เพิ่ม timeout 60 วินาที กันค้าง
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60)
            if r.status_code == 200:
                url = r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Upload Success (tmpfiles): {url}")
                return url
            else:
                print(f"⚠️ tmpfiles error: {r.status_code}")
    except Exception as e:
        print(f"⚠️ tmpfiles failed: {e}")

    # วิธีที่ 2: Catbox (Backup)
    try:
        print(f"☁️ Trying upload to Catbox (Backup)...")
        with open(filename, 'rb') as f:
            data = {'reqtype': 'fileupload'}
            r = requests.post('https://catbox.moe/user/api.php', data=data, files={'fileToUpload': f}, timeout=120)
            if r.status_code == 200:
                url = r.text
                print(f"✅ Upload Success (Catbox): {url}")
                return url
    except Exception as e:
        print(f"❌ All uploads failed: {e}")
        
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting Video Process...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Processing Scene {i+1}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            prompt = get_clean_prompt(scene)
            if not generate_image_hf(prompt, img_file):
                 create_placeholder_image(img_file)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5
                    
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
            
            print(f"[{task_id}] 📤 Uploading Video...")
            video_url = upload_to_host(output_filename)
            
            if video_url:
                print(f"[{task_id}] 🚀 Sending Webhook...")
                requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': video_url})
            else:
                print(f"[{task_id}] ❌ Upload Failed (Cannot send webhook)")
            
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