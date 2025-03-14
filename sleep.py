import cv2
import mediapipe as mp
import numpy as np
import time
import pygame
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from collections import deque
import requests

# ------------------------------
# Telegram Settings
# ------------------------------
bot_token = "7598156842:AAH9A3UTZmJMc3K0DBsK7zk3S8pOwz0bsk8"
chat_id = "970074787"

def send_telegram_notification():
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": "انتباه ...انتباه السائق يشعر بالنعاس وهو في حالة الخطر - يرجى اتخاذ التدابير اللازمة"}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram notification error:", e)

# ------------------------------
# Global Parameters and Variables
# ------------------------------
EAR_THRESHOLD = 0.25               # Default EAR (used until calibration)
CALIBRATION_FRAMES = 30            # Frames used for baseline calibration
MIN_CLOSED_DURATION = 2            # Seconds of closed eyes to trigger alarm/alert
WINDOW_SIZE = 45                   # Sliding window size (optional smoothing)

calibration_ears = []
calibrated = False
dynamic_threshold = EAR_THRESHOLD  # Will be updated after calibration
ear_window = deque(maxlen=WINDOW_SIZE)
closed_start_time = None

left_ear_val = None
right_ear_val = None

# Flag to send Telegram notification only once per detection
telegram_notified = False

# ------------------------------
# Initialize Pygame Mixer for Sound Alerts
# ------------------------------
pygame.mixer.init()
beep_sound = pygame.mixer.Sound("beep.mp3")    # Replace with your beep MP3 file
alarm_sound = pygame.mixer.Sound("alarm.mp3")    # Replace with your alarm MP3 file
beep_channel = pygame.mixer.Channel(0)
alarm_channel = pygame.mixer.Channel(1)

# ------------------------------
# Initialize MediaPipe Face Mesh
# ------------------------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
mp_drawing = mp.solutions.drawing_utils
# Draw the full mesh overlay in green.
drawing_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1, color=(0, 255, 0))
connection_spec = mp_drawing.DrawingSpec(thickness=1, color=(0, 255, 0))

# ------------------------------
# Define Eye Landmark Indices (from MediaPipe Face Mesh)
# ------------------------------
LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

def eye_aspect_ratio(landmarks, eye_indices, frame_width, frame_height):
    """Compute the Eye Aspect Ratio (EAR) for one eye."""
    pts = np.array([
        (landmarks[i].x * frame_width, landmarks[i].y * frame_height)
        for i in eye_indices
    ])
    dist_vertical1 = np.linalg.norm(pts[1] - pts[5])
    dist_vertical2 = np.linalg.norm(pts[2] - pts[4])
    dist_horizontal = np.linalg.norm(pts[0] - pts[3])
    ear = (dist_vertical1 + dist_vertical2) / (2.0 * dist_horizontal)
    return ear

# ------------------------------
# Initialize OpenCV Video Capture (global)
# ------------------------------
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise IOError("Cannot open webcam")

# ------------------------------
# Setup Tkinter GUI with Beautiful Design and Logos
# ------------------------------
window = tk.Tk()
window.title("Advanced AI-Based Drowsiness Detection for Enhanced Driver Safety")
window.geometry("1000x700")
window.configure(bg="#2e2e2e")

# Top frame for logos and title.
top_frame = ttk.Frame(window, padding=10)
top_frame.pack(side=tk.TOP, fill=tk.X)

# Load logo images using PIL.
try:
    left_logo_img = Image.open("qstss.png")
    right_logo_img = Image.open("moe.png")
except Exception as e:
    print("Error loading logos:", e)
    left_logo_img = right_logo_img = None

# Resize logos (adjust sizes as needed).
if left_logo_img:
    left_logo_img = left_logo_img.resize((220, 80))
    left_logo_tk = ImageTk.PhotoImage(left_logo_img)
else:
    left_logo_tk = None

if right_logo_img:
    right_logo_img = right_logo_img.resize((200, 80))
    right_logo_tk = ImageTk.PhotoImage(right_logo_img)
else:
    right_logo_tk = None

# Create labels for logos and title.
if left_logo_tk:
    left_logo_label = ttk.Label(top_frame, image=left_logo_tk, background="#2e2e2e")
    left_logo_label.pack(side=tk.LEFT, padx=10)
else:
    left_logo_label = ttk.Label(top_frame, text="", background="#2e2e2e")
    left_logo_label.pack(side=tk.LEFT, padx=10)

title_label = ttk.Label(top_frame, text="Advanced AI-Based Drowsiness Detection for Enhanced Driver Safety", font=("Helvetica", 24, "bold"),
                        background="#2e2e2e", foreground="black")
title_label.pack(side=tk.LEFT, expand=True)

if right_logo_tk:
    right_logo_label = ttk.Label(top_frame, image=right_logo_tk, background="#2e2e2e")
    right_logo_label.pack(side=tk.RIGHT, padx=10)
else:
    right_logo_label = ttk.Label(top_frame, text="", background="#2e2e2e")
    right_logo_label.pack(side=tk.RIGHT, padx=10)

# Video frame for displaying the video feed.
video_frame = ttk.Frame(window, padding=10)
video_frame.pack(expand=True, fill=tk.BOTH)
video_label = ttk.Label(video_frame)
video_label.pack(expand=True)

# Status label for messages.
status_label = ttk.Label(window, text="Status: Running", font=("Helvetica", 16),
                         background="#2e2e2e", foreground="lime")
status_label.pack(pady=10)

def update_frame():
    global calibrated, dynamic_threshold, closed_start_time, left_ear_val, right_ear_val, cap, telegram_notified
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        window.after(10, update_frame)
        return

    # Flip frame for mirror view.
    frame = cv2.flip(frame, 1)
    frame_height, frame_width = frame.shape[:2]
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb_frame)
    current_ear = None
    eyes_closed = False

    if results.multi_face_landmarks:
        for face_landmarks in results.multi_face_landmarks:
            # Draw the full mesh overlay (green).
            mp_drawing.draw_landmarks(
                image=frame,
                landmark_list=face_landmarks,
                connections=mp_face_mesh.FACEMESH_TESSELATION,
                landmark_drawing_spec=drawing_spec,
                connection_drawing_spec=connection_spec
            )
            # Compute EAR for each eye.
            left_ear_val = eye_aspect_ratio(face_landmarks.landmark, LEFT_EYE_INDICES, frame_width, frame_height)
            right_ear_val = eye_aspect_ratio(face_landmarks.landmark, RIGHT_EYE_INDICES, frame_width, frame_height)
            current_ear = (left_ear_val + right_ear_val) / 2.0

            # Display EAR values with bold black text on white background.
            l_text = f"Left Eye: {left_ear_val:.2f}"
            (l_text_w, l_text_h), _ = cv2.getTextSize(l_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(frame, (30, 30 - l_text_h - 5), (30 + l_text_w, 30 + 5), (255, 255, 255), -1)
            cv2.putText(frame, l_text, (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
            r_text = f"Right Eye: {right_ear_val:.2f}"
            (r_text_w, r_text_h), _ = cv2.getTextSize(r_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(frame, (30, 80 - r_text_h - 5), (30 + r_text_w, 80 + 5), (255, 255, 255), -1)
            cv2.putText(frame, r_text, (30, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
            break

    # Calibration Phase: Collect baseline EAR values.
    if not calibrated:
        if current_ear is not None:
            calibration_ears.append(current_ear)
        if len(calibration_ears) >= CALIBRATION_FRAMES:
            baseline_ear = sum(calibration_ears) / len(calibration_ears)
            dynamic_threshold = baseline_ear * 0.75  # Adjust factor as needed.
            calibrated = True
            print(f"Calibration complete. Baseline EAR: {baseline_ear:.2f}, Dynamic Threshold: {dynamic_threshold:.2f}")
            telegram_notified = False
    else:
        pass

    # Two Eyes Technique: Both eyes must be below the dynamic threshold.
    if left_ear_val is not None and right_ear_val is not None:
        if left_ear_val < dynamic_threshold and right_ear_val < dynamic_threshold:
            eyes_closed = True
        else:
            eyes_closed = False
    else:
        eyes_closed = False

    # Manage Sound Alarms Based on Duration.
    if eyes_closed:
        if closed_start_time is None:
            closed_start_time = time.time()
        elapsed = time.time() - closed_start_time
        if elapsed < MIN_CLOSED_DURATION:
            if not beep_channel.get_busy():
                beep_channel.play(beep_sound)
            if alarm_channel.get_busy():
                alarm_channel.stop()
        else:
            if not alarm_channel.get_busy():
                alarm_channel.play(alarm_sound, loops=-1)
            if beep_channel.get_busy():
                beep_channel.stop()
            # Send Telegram notification once when drowsiness is detected.
            if not telegram_notified:
                send_telegram_notification()
                telegram_notified = True
    else:
        closed_start_time = None
        if beep_channel.get_busy():
            beep_channel.stop()
        if alarm_channel.get_busy():
            alarm_channel.stop()
        telegram_notified = False

    # Draw status indicator circle at the top-right.
    indicator_radius = 60
    indicator_point = (frame_width - 60, 60)
    if eyes_closed and closed_start_time is not None and (time.time() - closed_start_time) >= MIN_CLOSED_DURATION:
        status_color = (0, 0, 255)
    else:
        status_color = (0, 255, 0)
    cv2.circle(frame, indicator_point, indicator_radius, status_color, -1)
    cv2.circle(frame, indicator_point, indicator_radius, (255, 255, 255), 2)

    # Display alert text at center with white background for 2 seconds after detection.
    if eyes_closed and closed_start_time is not None and (time.time() - closed_start_time) >= MIN_CLOSED_DURATION:
        alert_text = "DROWSINESS DETECTED!"
        (alert_w, alert_h), _ = cv2.getTextSize(alert_text, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
        alert_x = (frame_width - alert_w) // 2
        alert_y = (frame_height + alert_h) // 2
        cv2.rectangle(frame, (alert_x - 10, alert_y - alert_h - 10), (alert_x + alert_w + 10, alert_y + 10), (255, 255, 255), -1)
        cv2.putText(frame, alert_text, (alert_x, alert_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        # Keep the alert text for 2 seconds.
        if (time.time() - closed_start_time) < (MIN_CLOSED_DURATION + 2):
            status_label.config(text="Drowsiness Detected!", foreground="red")
        else:
            status_label.config(text="Alert: Awake", foreground="lime")
    else:
        status_label.config(text="Alert: Awake", foreground="lime")

    # Convert processed frame to PIL Image, then to ImageTk format.
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)
    imgtk = ImageTk.PhotoImage(image=img)
    video_label.imgtk = imgtk
    video_label.configure(image=imgtk)

    window.after(10, update_frame)

def on_closing():
    global cap
    cap.release()
    pygame.mixer.quit()
    window.destroy()

window.protocol("WM_DELETE_WINDOW", on_closing)

if __name__ == '__main__':
    from PIL import Image, ImageTk
    window.after(0, update_frame)
    window.mainloop()
