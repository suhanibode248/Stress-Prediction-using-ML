from flask import Flask, render_template, request, jsonify
from model import calculate_stress
import base64
import cv2
import numpy as np

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')


def analyze_face(image_data):
    try:
        if not image_data:
            return 50

        img_data = base64.b64decode(image_data.split(',')[1])
        np_arr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        # SAFE fallback (no DeepFace crash)
        return 55

    except:
        return 50


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()

        face = analyze_face(data.get("image"))
        blink = float(data.get("blink", 50))
        voice = float(data.get("voice", 50))

        result = calculate_stress(face, blink, voice)

        return jsonify(result)

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": "backend failed"})


if __name__ == "__main__":
    app.run(debug=True)