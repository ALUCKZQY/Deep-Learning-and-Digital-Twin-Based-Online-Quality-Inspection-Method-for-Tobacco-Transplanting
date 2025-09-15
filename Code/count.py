import cv2
from ultralytics import YOLO
import os
import time
import csv  

model_path = r"best.pt"  
input_video_path = r"input.mp4"  
output_video_path = r"output.mp4" 

count_right_to_left = True

if not os.path.exists(model_path):
    raise FileNotFoundError(f" {model_path} not exist")
if not os.path.exists(input_video_path):
    raise FileNotFoundError(f" {input_video_path} not exist")

model = YOLO(model_path)

cap = cv2.VideoCapture(input_video_path)

fps = cap.get(cv2.CAP_PROP_FPS) 
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) 
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))  
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  

target_fps = 15  
frame_interval = max(1, int(fps / target_fps)) 
actual_fps = fps / frame_interval 

scale_factor = 0.5  
new_width = int(width * scale_factor)
new_height = int(height * scale_factor)

if fps <= 0 or fps > 120: 
    fps = 30.0
    print(f"WARNING: FPS {fps} is invalid, defaulting to 30 FPS!")
print(f"Input video: original FPS={fps}, processed FPS={actual_fps:.2f} (process 1 frame every {frame_interval} frames)")
print(f"Resolution: original size = {width} x {height}, processed size = {new_width} x {new_height}")
print(f"Total number of frames = {total_frames}, Estimated number of frames to be processed = {total_frames//frame_interval}")

fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
out = cv2.VideoWriter(output_video_path, fourcc, target_fps, (width, height))  
if not out.isOpened():
    print("WARNING: mp4v encoding failed, trying XVID encoding...")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    output_video_path = output_video_path.replace('.mp4', '.avi')  
    out = cv2.VideoWriter(output_video_path, fourcc, target_fps, (width, height))
if not out.isOpened():
    raise RuntimeError("Check the encoding or path!")

frame_count = 0
seen_ids = set()
id_map = {}  
next_id = 1  

with open('crossing_records.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Label', 'Frame_Number'])

class_counters = {}  
prev_centers = {}  
line_x = new_width // 2 

start_time = time.time()

while cap.isOpened():
    frame_count += 1

    ret, frame = cap.read()
    if not ret:
        break

    if frame_count % frame_interval != 0:
        continue
        
    frame_start_time = time.time()

    frame_resized = cv2.resize(frame, (new_width, new_height))

    results = model.track(
        frame_resized,
        persist=True,  
        conf=0.4,      
        iou=0.5,      
        tracker="botsort.yaml", 
        half=True      
    )

    cv2.line(frame_resized, (line_x, 0), (line_x, new_height), (0, 0, 255), 2)

    frame_ids = [] 
    for result in results:
        boxes = result.boxes.xyxy.cpu().numpy()  
        confidences = result.boxes.conf.cpu().numpy()  
        classes = result.boxes.cls.cpu().numpy()  
        track_ids = result.boxes.id.cpu().numpy() if result.boxes.id is not None else [-1] * len(boxes)  

        for i in range(len(boxes)):
            x1, y1, x2, y2 = map(int, boxes[i]) 
            conf = confidences[i] 
            cls = int(classes[i]) 
            label = model.names[cls]  
            track_id = int(track_ids[i]) if track_ids[i] != -1 else -1  

            if track_id != -1 and track_id not in id_map:
                id_map[track_id] = next_id
                next_id += 1
            continuous_id = id_map.get(track_id, -1)

            frame_ids.append((track_id, continuous_id, label, conf))

            if track_id not in seen_ids and track_id != -1:
                seen_ids.add(track_id)

            if track_id != -1:
                curr_center_x = (x1 + x2) / 2
                if track_id in prev_centers:
                    prev_center_x = prev_centers[track_id]
                    if count_right_to_left:
                        if prev_center_x >= line_x and curr_center_x < line_x:
                            class_counters[label] = class_counters.get(label, 0) + 1
                            print(f"ID {continuous_id} ({label}) ！{label} Out: {class_counters[label]}")
                            with open('crossing_records.csv', 'a', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerow([label, frame_count])
                    else:
                        if prev_center_x <= line_x and curr_center_x > line_x:
                            class_counters[label] = class_counters.get(label, 0) + 1
                            print(f"ID {continuous_id} ({label}) ！{label} In: {class_counters[label]}")
                            with open('crossing_records.csv', 'a', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerow([label, frame_count])
                prev_centers[track_id] = curr_center_x
            cv2.rectangle(frame_resized, (x1, y1), (x2, y2), (0, 255, 0), 2)

            label_text = f"{label}  {conf:.2f}"

            cv2.putText(frame_resized, label_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    y_offset = 30
    for label, count in class_counters.items():
        cv2.putText(frame_resized, f"{label}  {count}", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        y_offset += 30

    if frame_ids:
        print(f"Frame {frame_count}: IDs = {[(tid, cid, label, f'{conf:.2f}') for tid, cid, label, conf in frame_ids]}")

    frame_output = cv2.resize(frame_resized, (width, height))
    out.write(frame_output)
    cv2.imshow("Detection", frame_resized)

    frame_time = time.time() - frame_start_time
    print(f"Frame {frame_count}/{total_frames} ({frame_count/total_frames*100:.1f}%): time={frame_time:.3f}s, FPS={1/frame_time:.2f}")

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
out.release()
cv2.destroyAllWindows()
