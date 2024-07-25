from flask import Flask, render_template, request, jsonify, Response, send_file
import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import threading
import time
import warnings
import joblib
import os

warnings.filterwarnings('ignore', category=UserWarning, module='google.protobuf')

app = Flask(__name__)

# Initializing Mediapipe Face Mesh and drawing utilities
mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils

# Global variables
data = []
trained_model = None
is_predicting = False
is_capturing = False
current_class = ""
num_samples = 0
samples_captured = 0
capturing_complete = False

# Personalized facial connections (extracted from Mediapipe)
FACE_CONNECTIONS = mp_face_mesh.FACEMESH_TESSELATION

# Video capture in a separate thread
class VideoCaptureThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.stopped = False

    def run(self):
        global data, is_capturing, num_samples, samples_captured, current_class, is_predicting, trained_model, capturing_complete

        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        with mp_face_mesh.FaceMesh(min_detection_confidence=0.5, min_tracking_confidence=0.5) as face_mesh:
            while not self.stopped:
                ret, frame = cap.read()
                if not ret:
                    break

                frame = cv2.flip(frame, 1)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(frame_rgb)

                if results.multi_face_landmarks:
                    landmarks = []

                    for face_landmarks in results.multi_face_landmarks:
                        for landmark in face_landmarks.landmark:
                            landmarks.extend([landmark.x, landmark.y, landmark.z])
                        mp_drawing.draw_landmarks(
                            frame, face_landmarks, FACE_CONNECTIONS,
                            mp_drawing.DrawingSpec(color=(80, 110, 10), thickness=1, circle_radius=1),
                            mp_drawing.DrawingSpec(color=(80, 256, 121), thickness=1, circle_radius=1)
                        )

                    if is_capturing and samples_captured < num_samples:
                        data.append([current_class] + landmarks)
                        samples_captured += 1
                        cv2.putText(frame, f'Capturing: {current_class} ({samples_captured}/{num_samples})', (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2, cv2.LINE_AA)
                        if samples_captured >= num_samples:
                            capturing_complete = True

                    if is_predicting and trained_model:
                        columns = [f'{i}_{axis}' for i in range(468) for axis in ['x', 'y', 'z']]
                        input_data = pd.DataFrame([landmarks], columns=columns)
                        prediction = trained_model.predict(input_data)[0]
                        cv2.putText(frame, f'Prediction: {prediction}', (10, 70),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)

                _, buffer = cv2.imencode('.jpg', frame)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        cap.release()

# Start the video capture thread
video_thread = VideoCaptureThread()
video_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(video_thread.run(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_capture', methods=['POST'])
def start_capture():
    global is_capturing, current_class, num_samples, samples_captured, data, capturing_complete

    capture_info = request.get_json()
    num_samples = int(capture_info['num_samples'])
    class_names = capture_info['class_names']

    for class_name in class_names:
        current_class = class_name
        samples_captured = 0
        is_capturing = True
        while samples_captured < num_samples:
            time.sleep(0.1)
        is_capturing = False

    return jsonify({'message': 'Capture completed.', 'success': True})

@app.route('/train_model', methods=['POST'])
def train_model():
    global trained_model

    # Check if data exists
    csv_file_path = 'facial_expressions.csv'

    if not os.path.exists(csv_file_path):
        return jsonify({'message': 'Please capture the data first.', 'success': False})

    # Read the CSV file
    df = pd.read_csv(csv_file_path)
    X = df.drop('label', axis=1)
    Y = df['label']

    # Divide the data into training and test sets (20% test, 80% training)
    X_train, X_test, y_train, y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

    # Training the model
    model = DecisionTreeClassifier()
    model.fit(X_train, y_train)
    trained_model = model
    
    # Predicting and calculating accuracy
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    # Save the model as an .h5 file
    joblib.dump(trained_model, 'modele_decision_tree.h5')

    return jsonify({'message': 'Model trained successfully.', 'success': True, 'accuracy': accuracy})

@app.route('/start_prediction', methods=['POST'])
def start_prediction():
    global is_predicting, trained_model

    if not os.path.exists('modele_decision_tree.h5'):
        return jsonify({'message': 'Train the model please.', 'success': False})

    trained_model = joblib.load('modele_decision_tree.h5')
    is_predicting = True
    return jsonify({'message': 'Prediction started.', 'success': True})

@app.route('/stop_prediction', methods=['POST'])
def stop_prediction():
    global is_predicting
    is_predicting = False
    return jsonify({'message': 'Prediction stopped.', 'success': True})

@app.route('/download_data', methods=['GET'])
def download_data():
    columns = ['label'] + [f'{i}_{axis}' for i in range(468) for axis in ['x', 'y', 'z']]
    df = pd.DataFrame(data, columns=columns)
    file_path = 'facial_expressions.csv'
    df.to_csv(file_path, index=False)

    return send_file(file_path, mimetype='text/csv', download_name='facial_expressions.csv', as_attachment=True)

@app.route('/download_model', methods=['GET'])
def download_model():
    return send_file('modele_decision_tree.h5', mimetype='application/octet-stream', download_name='modele_decision_tree.h5', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
