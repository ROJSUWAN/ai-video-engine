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
from huggingface_hub import InferenceClient # ✅ พระเอกของเรา
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

# 🔗 Webhook URL (อันเดิม)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# 🔑 Token ของคุณ (ใส่ให้แล้วครับ)
HF_TOKEN = "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"

# --- Helper Functions ---

def get_font(fontsize):
    try: return ImageFont.truetype("arial.ttf", fontsize)
    except: return ImageFont.load_default()

def create_placeholder_image(filename):
    img = Image.new('RGB', (720, 1280), color=(50, 50, 50))
    img.save(filename)

def generate_image_hf(prompt, filename):
    """🔥 สร้างภาพด้วย Flux.1 (Nano Banana) ผ่าน Token ของคุณ"""
    print(f"🎨 Generative AI Working on: {prompt[:30]}...")
    
    # รายชื่อโมเดล (ใช้ Flux Dev เป็นตัวหลัก)
    models = [
        "black-forest-labs/FLUX.1-dev",
        "stabilityai/stable-diffusion-xl-base-1.0"
    ]
    
    client = InferenceClient(token=HF_TOKEN)
    
    for model in models:
        try:
            # สั่งสร้างภาพ
            image = client.text_to_image(
                prompt,
                model=model,
                height=1024, 
                width=768 # สัดส่วนเกือบๆ 9:16
            )
            
            # Save และ Resize เป็น 720x1280 (TikTok Size)
            image = image.convert("RGB").resize((720, 1280))
            image.save(filename)
            print(f"✅ Image Created with {model}")
            return True
            
        except Exception as e:
            print(f"⚠️ Model {model} busy/error: {e}")
            time.sleep(1)
            
    return False

def get_clean_prompt(scene):
    """แปลงข้อมูลจาก n8n ให้เป็น Prompt สำหรับวาดรูป"""
    # 1. ถ้า image_url เป็น Link ของ Pollinations ให้แกะ Prompt ออกมา
    url = scene.get('image_url', '')
    if "pollinations" in url and "/prompt/" in url:
        try:
            return unquote(url.split("/prompt/")[1].split("?")[0])
        except: pass
        
    # 2. ถ้า image_url ยาวๆ (ไม่ใช่ link) ให้ใช้เลย
    if len(url) > 10 and not url.startswith("http"):
        return url
        
    # 3. ถ้าไม่มีอะไรเลย ให้ใช้ Script บรรยายภาพแทน
    return f"High quality realistic photo of {scene['script']}, cinematic lighting, 8k"

# ... (ส่วนเสียง create_voice_safe เหมือนเดิม) ...
async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try: tts = gTTS(text=text, lang='th'); tts.save(filename)
        except: pass

def create_text_clip(text, size=(720, 1280), duration=5):
    # Text แบบประหยัด RAM
    return ImageClip(np.array(Image.new('RGBA', size, (0,0,0,0)))).set_duration(duration)

def upload_to_temp_host(filename):
    try:
        with open(filename, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if r.status_code == 200:
                return r.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
    except: pass
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting (Hugging Face Mode)...")
    output_filename = f"video_{task_id}.mp4"
    
    try:
        valid_clips = []
        for i, scene in enumerate(scenes):
            gc.collect()
            print(f"[{task_id}] Scene {i+1}...")
            
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4"

            # 1. ✅ สร้างภาพ (ใช้ Logic ใหม่)
            prompt = get_clean_prompt(scene)
            if not generate_image_hf(prompt, img_file):
                 print("⚠️ Image Gen Failed, using placeholder")
                 create_placeholder_image(img_file)

            # 2. สร้างเสียง
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # 3. ตัดต่อ
            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5
                    
                    img_clip = ImageClip(img_file).set_duration(dur).resize((720, 1280))
                    video = img_clip.set_audio(audio)
                    
                    video.write_videofile(
                        clip_output, fps=15, codec='libx264', audio_codec='aac', 
                        preset='ultrafast', threads=2, logger=None
                    )
                    
                    if os.path.exists(clip_output) and os.path.getsize(clip_output) > 1000:
                        valid_clips.append(clip_output)
                    
                    video.close(); audio.close(); img_clip.close(); del video, audio, img_clip
                    gc.collect()
                except Exception as e: print(f"❌ Error Scene {i}: {e}")

        # 4. รวมไฟล์
        if valid_clips:
            print(f"[{task_id}] 🎞️ Merging {len(valid_clips)} clips...")
            clips = [VideoFileClip(c) for c in valid_clips]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_filename, fps=15, preset='ultrafast')
            
            video_url = upload_to_temp_host(output_filename)
            if video_url:
                print(f"[{task_id}] ✅ Success! Link: {video_url}")
                requests.post(N8N_WEBHOOK_URL, json={'task_id': task_id, 'status': 'success', 'video_url': video_url})
            
            final.close()
            for c in clips: c.close()
        else:
            print("❌ No clips created.")

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