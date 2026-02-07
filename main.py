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
import nest_asyncio # 👈 ต้องเพิ่มตัวนี้

# แก้ปัญหา Event Loop ชนกันใน Flask
nest_asyncio.apply()

app = Flask(__name__)

# ==========================================
# 🛠️ โซนเครื่องมือ Helper
# ==========================================

def get_font(fontsize):
    """ฟังก์ชันหา Font อัตโนมัติ (กันตาย)"""
    # 1. ลองหา Tahoma ที่เราอัปโหลดไป
    if os.path.exists("tahoma.ttf"):
        return ImageFont.truetype("tahoma.ttf", fontsize)
    
    # 2. ถ้าไม่มี ลองหาฟอนต์ภาษาไทยอื่นๆ ใน Linux (ถ้ามี)
    linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    ]
    for path in linux_fonts:
        if os.path.exists(path):
            return ImageFont.truetype(path, fontsize)
            
    # 3. ถ้าหาไม่เจอเลย ใช้ Default (อาจจะเป็นสี่เหลี่ยม แต่ไม่ Error)
    print("⚠️ หาฟอนต์ไม่เจอ! ใช้ฟอนต์ Default")
    return ImageFont.load_default()

def download_image(url, filename):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20) # เพิ่ม timeout
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            # ✅ เช็คว่าไฟล์รูปใช้ได้จริงไหม + แปลงเป็น RGB
            try:
                img = Image.open(filename).convert('RGB')
                img.save(filename)
                return True
            except Exception as img_err:
                print(f"❌ ไฟล์ที่โหลดมาไม่ใช่รูปภาพ: {img_err}")
                return False
        else:
            print(f"❌ โหลดรูปไม่ผ่าน Status Code: {response.status_code}")
    except Exception as e:
        print(f"💥 Error โหลดรูป: {e}")
    return False

async def create_voice_safe(text, filename):
    try:
        # ใช้เสียงผู้ชาย (Niwat)
        communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
        await communicate.save(filename)
    except Exception as e:
        print(f"⚠️ Edge TTS พัง ({e}) -> สลับใช้ Google TTS")
        try:
            tts = gTTS(text=text, lang='th')
            tts.save(filename)
        except Exception as g_err:
            print(f"❌ Google TTS ก็พัง: {g_err}")

def text_wrap(text, font, max_width):
    lines = []
    if not text: return lines
    
    for paragraph in text.split('\n'):
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            try:
                # Pillow เวอร์ชันใหม่ใช้ getlength
                if hasattr(font, 'getlength'):
                    width = font.getlength(test_line)
                else:
                    width = font.getsize(test_line)[0]
            except:
                width = 0

            if width <= max_width:
                current_line += char
            else:
                lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines

def create_text_clip(text, size=(1080, 1920), duration=5):
    fontsize = 45 
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    
    # ✅ เรียกใช้ฟังก์ชันหาฟอนต์ที่ปลอดภัย
    font = get_font(fontsize)

    max_text_width = size[0] - 100 
    lines = text_wrap(text, font, max_text_width)

    line_height = fontsize * 1.5
    total_height = len(lines) * line_height
    
    bottom_padding = 120 
    current_y = size[1] - total_height - bottom_padding

    # วาดกล่อง Subtitle
    if lines: # วาดเฉพาะเมื่อมีข้อความ
        box_padding = 15
        box_x1 = (size[0] - max_text_width) / 2 - box_padding
        box_x2 = box_x1 + max_text_width + (box_padding*2)
        box_y1 = current_y - box_padding
        box_y2 = current_y + total_height + box_padding
        
        overlay = Image.new('RGBA', size, (0,0,0,0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_overlay.rectangle([box_x1, box_y1, box_x2, box_y2], fill=(0,0,0,150))
        img = Image.alpha_composite(img, overlay)
        
        # วาดตัวหนังสือ
        draw = ImageDraw.Draw(img)
        for line in lines:
            try:
                if hasattr(font, 'getlength'):
                    w = font.getlength(line)
                else:
                    w = font.getsize(line)[0]
            except:
                w = 0
                
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
        # Fallback กรณีส่งมาแบบเดี่ยว
        scenes_data = [{
            "script": data.get('script', 'Test Script'),
            "image_url": data.get('image_url', '')
        }]

    task_id = str(uuid.uuid4())
    output_filename = f"final_{task_id}.mp4"
    
    generated_clips = []
    temp_files = []

    try:
        for i, scene in enumerate(scenes_data):
            print(f"🎬 กำลังประมวลผลฉากที่ {i+1}...")
            
            script = scene.get('script', '')
            image_url = scene.get('image_url', '')
            
            scene_img = f"temp_{task_id}_s{i}.jpg"
            scene_audio = f"temp_{task_id}_s{i}.mp3"
            temp_files.extend([scene_img, scene_audio])

            # 1. โหลดรูป
            print(f"   ⬇️ กำลังโหลดรูป: {image_url[:30]}...")
            if not download_image(image_url, scene_img):
                print(f"   ⚠️ ข้ามฉากที่ {i+1} เพราะโหลดรูปไม่ได้")
                continue

            # 2. สร้างเสียง
            print(f"   🔊 กำลังสร้างเสียง...")
            # ใช้ nest_asyncio ช่วยตรงนี้
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(create_voice_safe(script, scene_audio))
            
            if not os.path.exists(scene_audio) or os.path.getsize(scene_audio) == 0:
                print(f"   ⚠️ ข้ามฉากที่ {i+1} เพราะสร้างเสียงไม่ได้")
                continue

            # 3. รวมร่าง
            try:
                audio_clip = AudioFileClip(scene_audio)
                duration = audio_clip.duration + 0.5
                
                img_clip = ImageClip(scene_img).set_duration(duration)
                
                # Crop 9:16
                if img_clip.w / img_clip.h > 9/16:
                    img_clip = img_clip.resize(height=1920)
                    img_clip = img_clip.crop(x_center=img_clip.w/2, width=1080)
                else:
                    img_clip = img_clip.resize(width=1080)
                    img_clip = img_clip.crop(y_center=img_clip.h/2, height=1920)

                txt_clip = create_text_clip(script, duration=duration)
                
                scene_video = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio_clip)
                generated_clips.append(scene_video)
                print(f"   ✅ ฉากที่ {i+1} สำเร็จ!")
                
            except Exception as clip_err:
                print(f"   ❌ Error ตอนตัดต่อฉาก {i+1}: {clip_err}")
                continue

        if generated_clips:
            print(f"🎞️ กำลัง Render วิดีโอรวม ({len(generated_clips)} ฉาก)...")
            final_video = concatenate_videoclips(generated_clips)
            
            # ลด FPS เหลือ 15 เพื่อประหยัด RAM บน Cloud
            final_video.write_videofile(output_filename, fps=15, codec='libx264', audio_codec='aac', logger=None)
            
            print("🎉 เสร็จสมบูรณ์! กำลังส่งไฟล์กลับ...")
            return send_file(output_filename, mimetype='video/mp4')
        else:
            print("❌ ไม่มีฉากไหนสำเร็จเลย")
            return jsonify({"status": "error", "message": "ไม่สามารถสร้างคลิปได้เลย (รูปหรือเสียงอาจมีปัญหา)"}), 500

    except Exception as e:
        print(f"💥 Critical Error: {e}")
        import traceback
        traceback.print_exc() # ปริ้น Error ยาวๆ ออกมาดู
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        # ล้างขยะ
        print("🧹 Cleaning up temp files...")
        for f in temp_files:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass
        if os.path.exists(output_filename):
            try: os.remove(output_filename)
            except: pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)