# app.py
import os
import sys
import json
import requests
import threading
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
from pexels_api import API
from gtts import gTTS
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips

# --- CẤU HÌNH ---
load_dotenv()
app = Flask(__name__)
CORS(app) 

# Cấu hình các API keys
try:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        print("Lỗi: Vui lòng thiết lập GEMINI_API_KEY và PEXELS_API_KEY trong Environment Variables.")
    
    genai.configure(api_key=GEMINI_API_KEY)
    pexels_api = API(PEXELS_API_KEY)
except Exception as e:
    print(f"Lỗi cấu hình API: {e}")

# --- CÁC HÀM CHỨC NĂNG ---

def generate_script_from_gemini(topic):
    print(f"🎬 Đang tạo kịch bản cho chủ đề: '{topic}'...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    Tạo kịch bản cho video ngắn khoảng 1 phút về '{topic}', chia thành 4 cảnh.
    Với mỗi cảnh, cung cấp "voiceover" (lời bình tiếng Việt, 20-30 từ) và "search_keyword" (từ khóa tiếng Anh, 2-3 từ để tìm video).
    Trả lời bằng JSON hợp lệ.
    {{
      "scenes": [
        {{"voiceover": "...", "search_keyword": "..."}},
        {{"voiceover": "...", "search_keyword": "..."}}
      ]
    }}
    """
    try:
        response = model.generate_content(prompt)
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        script = json.loads(json_text)
        print("✅ Kịch bản đã được tạo.")
        return script['scenes']
    except Exception as e:
        print(f"Lỗi khi tạo kịch bản: {e}")
        return None

def download_video_from_pexels(query, file_prefix):
    print(f"🔎 Đang tìm video cho '{query}'...")
    try:
        pexels_api.search(query, page=1, results_per_page=1, type_='videos')
        videos = pexels_api.get_entries()
        if not videos:
            print(f"⚠️ Không tìm thấy video, dùng 'nature' thay thế.")
            pexels_api.search('nature', page=1, results_per_page=1, type_='videos')
            videos = pexels_api.get_entries()
            if not videos: return None
        
        video_url = videos[0].video_files[0].link
        video_path = f"{file_prefix}_video.mp4"
        response = requests.get(video_url, stream=True)
        if response.status_code == 200:
            with open(video_path, 'wb') as f: f.write(response.content)
            print(f"✅ Đã tải xong video.")
            return video_path
        return None
    except Exception as e:
        print(f"Lỗi khi tải video Pexels: {e}")
        return None

def create_audio_from_text(text, file_prefix):
    print(f"🎤 Đang tạo giọng nói...")
    try:
        tts = gTTS(text, lang='vi', slow=False)
        audio_path = f"{file_prefix}_audio.mp3"
        tts.save(audio_path)
        print(f"✅ Giọng nói đã được tạo.")
        return audio_path
    except Exception as e:
        print(f"Lỗi khi tạo audio: {e}")
        return None

def create_final_video(video_paths, audio_paths, output_filename):
    print("🎬 Đang dựng video cuối cùng...")
    clips = []
    for video_path, audio_path in zip(video_paths, audio_paths):
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration + 1.0 
        video_clip = video_clip.subclip(0, duration).set_audio(audio_clip)
        clips.append(video_clip)
    
    if not clips: return None
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(output_filename, codec="libx264", audio_codec="aac")
    print(f"🎉 Video tạm đã được tạo: {output_filename}")
    return output_filename

def upload_to_gofile(file_path):
    print(f"☁️ Đang tải file '{file_path}' lên Gofile...")
    try:
        # Lấy server tốt nhất để tải lên
        server_response = requests.get("https://api.gofile.io/getServer")
        server_data = server_response.json()
        if server_data["status"] != "ok":
            print("Lỗi: Không thể lấy Gofile server.")
            return None
        server = server_data["data"]["server"]
        
        # Tải file lên
        with open(file_path, 'rb') as f:
            files = {'file': f}
            upload_response = requests.post(f"https://{server}.gofile.io/uploadFile", files=files)
        
        upload_data = upload_response.json()
        if upload_data["status"] == "ok":
            download_link = upload_data["data"]["downloadPage"]
            print(f"✅✅✅ LINK TẢI VIDEO: {download_link} ✅✅✅")
            return download_link
        else:
            print(f"Lỗi khi tải file lên: {upload_data.get('data', {}).get('error', 'Unknown error')}")
            return None
    except Exception as e:
        print(f"Lỗi khi tải file lên Gofile: {e}")
        return None

def cleanup_temp_files(files):
    print("🧹 Đang dọn dẹp file tạm...")
    for f in files:
        if f and os.path.exists(f):
            os.remove(f)
    print("✅ Dọn dẹp hoàn tất.")

def video_creation_process(topic, session_id):
    """Quy trình tạo video hoàn chỉnh."""
    print(f"--- BẮT ĐẦU TẠO VIDEO CHO '{topic}' (ID: {session_id}) ---")
    scenes = generate_script_from_gemini(topic)
    if not scenes:
        print("--- KẾT THÚC SỚM do không tạo được kịch bản ---")
        return
        
    temp_files = []
    video_paths = []
    audio_paths = []
    
    for i, scene in enumerate(scenes):
        file_prefix = f"temp_{session_id}_{i}"
        video_path = download_video_from_pexels(scene['search_keyword'], file_prefix)
        audio_path = create_audio_from_text(scene['voiceover'], file_prefix)
        
        if video_path and audio_path:
            video_paths.append(video_path)
            audio_paths.append(audio_path)
            temp_files.extend([video_path, audio_path])
    
    if video_paths and audio_paths:
        output_filename = f"final_{session_id}.mp4"
        temp_files.append(output_filename)
        
        final_video_path = create_final_video(video_paths, audio_paths, output_filename)
        if final_video_path:
            upload_to_gofile(final_video_path)

    cleanup_temp_files(temp_files)
    print(f"--- QUY TRÌNH HOÀN TẤT CHO '{topic}' (ID: {session_id}) ---")

# --- API ENDPOINT ---
@app.route('/')
def index():
    return "Video Creator API is running!"

@app.route('/api/create_video', methods=['POST'])
def handle_create_video():
    data = request.json
    topic = data.get('topic')
    if not topic:
        return jsonify({"error": "Vui lòng cung cấp chủ đề (topic)."}), 400

    session_id = os.urandom(4).hex()
    thread = threading.Thread(target=video_creation_process, args=(topic, session_id))
    thread.start()
    
    return jsonify({"message": f"Đã nhận yêu cầu cho '{topic}'. Video đang được tạo trong nền. Hãy theo dõi logs trên server Render để nhận link tải về."})

# Chạy server (chỉ dùng cho local, trên Render sẽ dùng Gunicorn)
if __name__ == '__main__':
    app.run(debug=True, port=5000)