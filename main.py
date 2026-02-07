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
import gc # Garbage Collector

nest_asyncio.apply()
app = Flask(__name__)

# 🔗 Webhook URL (อันเดิม)
N8N_WEBHOOK_URL = "https://primary-production-f87f.up.railway.app/webhook-test/receive-video"

# --- Helper Functions (เหมือนเดิม Copy มาได้เลย) ---
# ... (ใส่ get_font, create_placeholder_image, download_image, create_voice_safe, create_text_clip ไว้ตรงนี้) ...
# ... (เพื่อความกระชับ ผมละไว้ในฐานที่เข้าใจนะครับ ถ้าไม่มีบอกผมได้เดี๋ยวแปะตัวเต็มให้) ...

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
    try:
        print(f"☁️ Uploading {filename}...")
        with open(filename, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if response.status_code == 200:
                url = response.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Link: {url}")
                return url
    except Exception as e:
        print(f"❌ Upload Error: {e}")
    return None

def process_video_background(task_id, scenes):
    print(f"[{task_id}] 🚀 Low RAM Mode Starting...")
    output_filename = f"video_{task_id}.mp4"
    temp_files = []
    
    try:
        # 🔥 เปลี่ยนวิธี: สร้างทีละไฟล์ย่อยๆ แล้วค่อยเอามาต่อกัน (Concatenate)
        # วิธีนี้ประหยัด RAM กว่าการถือ Clips ทั้งหมดไว้ในมือ
        
        clip_files = [] # เก็บชื่อไฟล์วิดีโอย่อย
        
        for i, scene in enumerate(scenes):
            print(f"[{task_id}] Processing Scene {i+1}...")
            img_file = f"temp_{task_id}_{i}.jpg"
            audio_file = f"temp_{task_id}_{i}.mp3"
            clip_output = f"clip_{task_id}_{i}.mp4" # ไฟล์ย่อย
            
            temp_files.extend([img_file, audio_file])
            clip_files.append(clip_output)

            # 1. Prepare Assets
            if not download_image(scene['image_url'], img_file):
                 create_placeholder_image(img_file, "Image Error")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(scene['script'], audio_file))

            # 2. Render Small Clip immediately (Render แล้วเซฟเลย ไม่เก็บใน RAM)
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
                    
                    # 🔥 Write immediately!
                    video.write_videofile(
                        clip_output, 
                        fps=15, # ลด FPS เหลือ 15 พอสำหรับ TikTok
                        codec='libx264', 
                        audio_codec='aac', 
                        preset='ultrafast',
                        threads=2,
                        logger=None # ปิด log รกๆ
                    )
                    
                    # คืน RAM ทันที
                    video.close()
                    del video, img_clip, txt_clip, audio
                    gc.collect() 
                    
                except Exception as e: 
                    print(f"❌ Error Scene {i}: {e}")

        # 3. Concatenate all clips (ต่อไฟล์ย่อย)
        if clip_files:
            print(f"[{task_id}] 🎞️ Merging {len(clip_files)} clips...")
            
            # ใช้ method ของ moviepy แบบประหยัด ram
            clips = [VideoFileClip(c) for c in clip_files]
            final = concatenate_videoclips(clips, method="compose") # compose ปลอดภัยกว่า
            
            final.write_videofile(
                output_filename, 
                fps=15, 
                codec='libx264', 
                audio_codec='aac', 
                preset='ultrafast', 
                threads=2
            )
            
            # 4. Upload & Send
            video_url = upload_to_temp_host(output_filename)
            if video_url:
                print(f"[{task_id}] 🚀 Sending Webhook...")
                requests.post(N8N_WEBHOOK_URL, json={
                    'task_id': task_id, 
                    'status': 'success',
                    'video_url': video_url
                })
            
            # Close all
            final.close()
            for c in clips: c.close()
            
    except Exception as e:
        print(f"[{task_id}] Error: {e}")
    finally:
        # Cleanup ALL temp files
        all_temps = temp_files + [output_filename]
        # ต้องลบไฟล์ clip ย่อยๆ ด้วย (แต่ในตัวแปร local เข้าถึงยาก ให้ปล่อยไปก่อนหรือเพิ่ม logic ลบ)
        try:
            for f in os.listdir():
                if f.startswith(f"clip_{task_id}") or f.startswith(f"temp_{task_id}") or f.startswith(f"video_{task_id}"):
                    try: os.remove(f)
                    except: pass
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