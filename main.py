from flask import Flask, request, jsonify, send_file
import os
import uuid
from moviepy.editor import *
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import requests
import edge_tts
import asyncio
from gtts import gTTS

app = Flask(__name__)

# ==========================================
# 🛠️ โซนเครื่องมือ Helper
# ==========================================

def download_image(url, filename):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"💥 Error โหลดรูป: {e}")
    return False

async def create_voice_safe(text, filename):
    try:
        # ใช้เสียงผู้ชาย (Niwat)
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except:
        print("⚠️ Edge TTS พัง ใช้ Google แทน")
        tts = gTTS(text=text, lang='th')
        tts.save(filename)

def text_wrap(text, font, max_width):
    lines = []
    for paragraph in text.split('\n'):
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            try:
                width = font.getlength(test_line)
            except:
                width, _ = font.getsize(test_line)

            if width <= max_width:
                current_line += char
            else:
                lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines

# --- 🔄 ฟังก์ชันสร้างข้อความ (ปรับปรุงใหม่) ---
def create_text_clip(text, size=(1080, 1920), duration=5):
    # 1. 🔻 ปรับขนาดฟอนต์ให้เล็กลง (จาก 65 เหลือ 45)
    fontsize = 45 
    
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    font_path = "tahoma.ttf"
    try:
        font = ImageFont.truetype(font_path, fontsize)
    except:
        font = ImageFont.load_default()

    # ขอบเขตข้อความ (เพิ่มความกว้างให้บรรทัดยาวขึ้นได้อีกนิด)
    max_text_width = size[0] - 100 
    lines = text_wrap(text, font, max_text_width)

    # คำนวณความสูงรวมของข้อความ
    line_height = fontsize * 1.5
    total_height = len(lines) * line_height
    
    # 2. 🔻 ปรับตำแหน่งให้ต่ำลง (ลด Padding จาก 400 เหลือ 120)
    bottom_padding = 120 
    current_y = size[1] - total_height - bottom_padding

    # วาดกล่องพื้นหลังสีดำจางๆ (Subtitle Box)
    box_padding = 15
    box_x1 = (size[0] - max_text_width) / 2 - box_padding
    box_x2 = box_x1 + max_text_width + (box_padding*2)
    box_y1 = current_y - box_padding
    box_y2 = current_y + total_height + box_padding
    
    overlay = Image.new('RGBA', size, (0,0,0,0))
    draw_overlay = ImageDraw.Draw(overlay)
    # ปรับความเข้มพื้นหลัง (150 คือความทึบแสง 0-255)
    draw_overlay.rectangle([box_x1, box_y1, box_x2, box_y2], fill=(0,0,0,150))
    img = Image.alpha_composite(img, overlay)
    
    # วาดตัวหนังสือ
    draw = ImageDraw.Draw(img)
    for line in lines:
        try:
            w = font.getlength(line)
        except:
            w = font.getsize(line)[0]
            
        x = (size[0] - w) / 2
        draw.text((x, current_y), line, font=font, fill="white")
        current_y += line_height

    return ImageClip(np.array(img)).set_duration(duration)

# ==========================================
# 🌐 API Routes
# ==========================================

@app.route('/create-video', methods=['POST'])
def api_create_video():
    data = request.json
    print(f"\n📩 ได้รับงาน Storyboard ใหม่!")
    
    scenes_data = data.get('scenes', [])
    if not scenes_data:
        scenes_data = [{
            "script": data.get('script', 'ไม่มีข้อความ'),
            "image_url": data.get('image_url', '')
        }]

    task_id = str(uuid.uuid4())
    output_filename = f"final_{task_id}.mp4"
    
    generated_clips = []
    temp_files = []

    try:
        for i, scene in enumerate(scenes_data):
            print(f"🎬 กำลังสร้างฉากที่ {i+1}...")
            
            script = scene.get('script', '')
            image_url = scene.get('image_url', '')
            
            scene_img = f"temp_{task_id}_s{i}.jpg"
            scene_audio = f"temp_{task_id}_s{i}.mp3"
            temp_files.extend([scene_img, scene_audio])

            if not download_image(image_url, scene_img):
                print(f"⚠️ ข้ามฉากที่ {i+1}")
                continue

            asyncio.run(create_voice_safe(script, scene_audio))
            
            if not os.path.exists(scene_audio):
                continue

            audio_clip = AudioFileClip(scene_audio)
            duration = audio_clip.duration + 0.5
            
            img_clip = ImageClip(scene_img).set_duration(duration)
            if img_clip.w / img_clip.h > 9/16:
                img_clip = img_clip.resize(height=1920)
                img_clip = img_clip.crop(x_center=img_clip.w/2, width=1080)
            else:
                img_clip = img_clip.resize(width=1080)
                img_clip = img_clip.crop(y_center=img_clip.h/2, height=1920)

            txt_clip = create_text_clip(script, duration=duration)
            
            scene_video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio_clip)
            generated_clips.append(scene_video)

        if generated_clips:
            print(f"🎞️ กำลังรวม {len(generated_clips)} ฉากเข้าด้วยกัน...")
            final_video = concatenate_videoclips(generated_clips)
            final_video.write_videofile(output_filename, fps=24, logger=None)
            print("🎉 เสร็จสมบูรณ์!")
            return send_file(output_filename, mimetype='video/mp4')
        else:
            return jsonify({"status": "error", "message": "สร้างวิดีโอไม่ได้เลย"}), 500

    except Exception as e:
        print(f"💥 Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        for f in temp_files:
            if os.path.exists(f): os.remove(f)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)