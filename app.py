import os
import cv2
import numpy as np
from io import BytesIO
from flask import Flask, render_template, request, send_file, Response, jsonify
from ultralytics import YOLO

# ── DISABLE GPU ───────────────────────────────────────────────────────────
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # Disable GPU globally

# ── CONFIG ────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')
MODEL_PATH = os.path.join(BASE_DIR, 'weights', 'best.pt')

CONF_THRESHOLD = 0.5  # threshold for detection

# ── CLASS OVERRIDE ────────────────────────────────────────────────────────
CLASS_MAP = {
    0: 'Smoke',
    1: 'Fire'
}

COLORS = {
    'Fire': (0, 0, 255),
    'Smoke': (0, 255, 255)
}

# ── APP SETUP ─────────────────────────────────────────────────────────────
app = Flask(__name__)
model = YOLO(MODEL_PATH)
model.to('cpu')

# ── HOME ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ── IMAGE PROCESSING ──────────────────────────────────────────────────────
@app.route('/upload_image', methods=['POST'])
def upload_image():
    try:
        file = request.files.get('file')
        if not file:
            return "No file uploaded", 400

        img_bytes = file.read()
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return "Image decode failed", 400

        results = model(img)[0]

        detected = False
        for det in results.boxes:
            conf = float(det.conf[0])
            if conf >= CONF_THRESHOLD:
                detected = True
                cls_id = int(det.cls[0])
                cls_name = CLASS_MAP.get(cls_id, f"Class {cls_id}")
                x1, y1, x2, y2 = map(int, det.xyxy[0])
                color = COLORS.get(cls_name, (255, 255, 255))

                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                text = f"{cls_name} {conf:.2f}"
                cv2.putText(img, text, (x1, y2 + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        if not detected:
            cv2.putText(img, "No Fire", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

        _, buf = cv2.imencode('.png', img)
        return send_file(BytesIO(buf.tobytes()), mimetype='image/png')

    except Exception as e:
        return str(e), 500


@app.route('/upload_video', methods=['POST'])
def upload_video():
    file = request.files['file']
    if not file:
        return "No file uploaded", 400

    save_path = os.path.join(UPLOAD_DIR, 'live_input.mp4')
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file.save(save_path)

    app.config['CURRENT_VIDEO_PATH'] = save_path
    return jsonify({"stream_url": "/video_feed"})


# ── SERVE PROCESSED VIDEO FILE ────────────────────────────────────────────
@app.route('/video_file/<video_id>')
def serve_video(video_id):
    output_path = os.path.join(OUTPUT_DIR, f'{video_id}_output.mp4')
    return send_file(output_path, mimetype='video/mp4', as_attachment=False)


# ── VIDEO PROCESSING FUNCTION ─────────────────────────────────────────────
def gen_live_frames(video_path):
    cap = cv2.VideoCapture(video_path)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        results = model(frame)[0]
        detected = False

        for det in results.boxes:
            conf = float(det.conf[0])
            if conf >= CONF_THRESHOLD:
                detected = True
                cls_id = int(det.cls[0])
                cls_name = CLASS_MAP.get(cls_id, f"Class {cls_id}")
                x1, y1, x2, y2 = map(int, det.xyxy[0])
                color = COLORS.get(cls_name, (255, 255, 255))

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                text = f"{cls_name} {conf:.2f}"
                cv2.putText(frame, text, (x1, y2 + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        if not detected:
            cv2.putText(frame, "No Fire", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()


@app.route('/video_feed')
def video_feed():
    video_path = app.config.get('CURRENT_VIDEO_PATH')
    return Response(gen_live_frames(video_path),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# ── RUN ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
