from flask import Flask, request, jsonify
import threading
import uuid
import os
import time
import requests
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
import asyncio
from gtts import gTTS
import nest_asyncio

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Webhook URL (อันเดิมของคุณ)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# --- Helper Functions (เหมือนเดิม) ---

def get_font(fontsize):
    font_names = ["tahoma.ttf", "arial.ttf", "leelawad.ttf"]
    for name in font_names:
        if os.path.exists(name): return ImageFont.truetype(name, fontsize)
    return ImageFont.load_default()

def create_placeholder_image(filename, text="No Image"):
    img = Image.new('RGB', (1080, 1920), color=(30, 30, 30))
    d = ImageDraw.Draw(img)
    try:
        f = get_font(60)
        d.text((100, 900), text, fill=(255, 100, 100), font=f)
    except: pass
    img.save(filename)

def download_image(url, filename):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://google.com'
        }
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=20, verify=False)
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    Image.open(filename).convert('RGB').save(filename)
                    return True
            except: time.sleep(2)
        return False
    except: return False

async def create_voice_safe(text, filename):
    try:
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        try:
            tts = gTTS(text=text, lang='th')
            tts.save(filename)
        except: pass

def create_text_clip(text, size=(1080, 1920), duration=5):
    fontsize = 50
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    font = get_font(fontsize)
    lines = []
    temp_line = ""
    for word in text.split(' '):
        if len(temp_line + word) < 25: temp_line += word + " "
        else:
            lines.append(temp_line)
            temp_line = word + " "
    lines.append(temp_line)
    text_height = len(lines) * 70
    start_y = 1400 
    overlay = Image.new('RGBA', size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([50, start_y - 20, 1030, start_y + text_height + 20], fill=(0,0,0,160))
    img = Image.alpha_composite(img, overlay)
    draw_text = ImageDraw.Draw(img)
    cur_y = start_y
    for line in lines:
        try: draw_text.text((80, cur_y), line, font=font, fill="white")
        except: pass
        cur_y += 70
    return ImageClip(np.array(img)).set_duration(duration)

def upload_to_temp_host(filename):
    """ฝากไฟล์ไว้ที่เว็บ tmpfiles.org"""
    try:
        print(f"☁️ Uploading {filename}...")
        with open(filename, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if response.status_code == 200:
                data = response.json()
                url = data['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Upload Link: {url}")
                return url
    except Exception as e:
        print(f"❌ Upload Error: {e}")
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Starting...")
    output_filename = f"video_{task_id}.mp4"
    temp_files = []
    
    try:
        clips = []
        for i, scene in enumerate(scenes):
            print(f"[{task_id}] Scene {i+1}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            temp_files.extend([img_file, audio_file])

            if not download_image(scene['image_url'], img_file):
                 create_placeholder_image(img_file, "Image Error")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            if os.path.exists(audio_file) and os.path.exists(img_file):
                try:
                    audio = AudioFileClip(audio_file)
                    dur = audio.duration + 0.5 
                    img_clip = ImageClip(img_file).set_duration(dur)
                    if img_clip.w / img_clip.h > 9/16:
                        img_clip = img_clip.resize(height=1920).crop(x_center=img_clip.w/2, width=1080)
                    else:
                        img_clip = img_clip.resize(width=1080).crop(y_center=img_clip.h/2, height=1920)
                    txt_clip = create_text_clip(scene['script'], duration=dur)
                    video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio)
                    clips.append(video)
                except: pass

        if clips:
            print(f"[{task_id}] 🎞️ Rendering (Safe Mode)...")
            final = concatenate_videoclips(clips)
            
            # 🔥 แก้ไขจุดที่ทำให้ค้าง (ใช้ ultrafast + mp3)
            final.write_videofile(
                output_filename, 
                fps=24, 
                codec='libx264', 
                audio_codec='libmp3lame', # เปลี่ยนเป็น mp3 เพื่อความเสถียร
                preset='ultrafast',       # เร็วและไม่กิน RAM จนค้าง
                threads=4                 # ใช้ 4 หัวช่วยกันทำงาน
            )
            
            # ส่งลิงก์กลับไป
            video_url = upload_to_temp_host(output_filename)
            if video_url:
                print(f"[{task_id}] 🚀 Sending Webhook...")
                requests.post(N8N_WEBHOOK_URL, json={
                    'task_id': task_id, 
                    'status': 'success',
                    'video_url': video_url
                })
            else:
                print("Failed to get link")

    except Exception as e:
        print(f"[{task_id}] Error: {e}")
    finally:
        for f in temp_files:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass
        if os.path.exists(output_filename): 
            try: os.remove(output_filename)
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