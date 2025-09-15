import subprocess
import time
import csv
import pandas as pd
from datetime import datetime
import os
import threading
from queue import Queue
import hashlib
import detection 
import matplotlib.pyplot as plt 
import unity_communication  

class RecordProcessor:
    def __init__(self):
        self.processed_records = set()  
        self.lock = threading.Lock()    
        self.queue = Queue()            
        self.timestamps_df = None
        self.gps_df = None
        self.is_running = True
        self.temp_file = 'temp_crossing_records.csv' 
        self.unity_comm = None  

    def initialize_data(self):
        print("loading timestamp and GPS data...")
        self.timestamps_df = pd.read_csv('frames_timestamps.csv')
        self.gps_df = pd.read_csv('GNSS.csv')
        self.gps_df['datetime'] = pd.to_datetime(self.gps_df['datetime'])
        print("loading completed！")

    def start_unity_server(self):
        print("start Unity communicate...")
        self.unity_comm = unity_communication.UnityCommManager(host='127.0.0.1', port=8888)
        self.unity_comm.start_server()
        print("waiting for connect...")

    def get_record_hash(self, label, frame_number):
        record_str = f"{label}_{frame_number}"
        return hashlib.md5(record_str.encode()).hexdigest()

    def get_timestamp_for_frame(self, frame_number):
        try:
            row = self.timestamps_df[self.timestamps_df['frame_number'] == int(frame_number)].iloc[0]
            return row['timestamp']
        except (IndexError, KeyError):
            return None

    def get_gps_for_timestamp(self, timestamp):
        try:
            timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            closest_row = self.gps_df.iloc[(self.gps_df['datetime'] - timestamp_dt).abs().argsort()[:1]]
            
            return {
                'latitude': float(closest_row['latitude'].iloc[0]),
                'longitude': float(closest_row['longitude'].iloc[0]),
                'speed': float(closest_row['speed'].iloc[0]),
                'course': float(closest_row['course'].iloc[0]),
                'timestamp': closest_row['datetime'].iloc[0].isoformat()
            }
        except Exception as e:
            print(f"Error getting GPS data: {e}")
            return None

    def update_record_with_gps(self, label, frame_number):
        timestamp = self.get_timestamp_for_frame(frame_number)
        if timestamp:
            gps_data = self.get_gps_for_timestamp(timestamp)
            if gps_data:
                return [str(label), str(frame_number), str(gps_data['timestamp']), 
                       str(gps_data['latitude']), str(gps_data['longitude']), 
                       str(gps_data['speed']), str(gps_data['course'])]
        return None

    def process_record(self, label, frame_number):
        try:
            record_hash = self.get_record_hash(str(label), str(frame_number))
     
            with self.lock:
                if record_hash in self.processed_records:
                    return
                self.processed_records.add(record_hash)
              
            updated_record = self.update_record_with_gps(label, frame_number)
            if updated_record:
                all_records = []
                header = ['Label', 'Frame_Number', 'Timestamp', 'Latitude', 'Longitude', 'Speed', 'Course']

                if os.path.exists('crossing_records.csv'):
                    with open('crossing_records.csv', 'r', newline='') as f:
                        reader = csv.reader(f)
                        file_header = next(reader)  

                        if len(file_header) <= 2: 
                            all_records = [] 
                        else:
                            header = file_header  
                            all_records = list(reader)

                record_updated = False
                for i, record in enumerate(all_records):
                    if len(record) >= 2 and str(record[0]) == str(label) and str(record[1]) == str(frame_number):
                        all_records[i] = updated_record
                        record_updated = True
                        break

                if not record_updated:
                    all_records.append(updated_record)

                with open('crossing_records.csv', 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(all_records)

                print(f"\n refresh：")
                print(f"label: {label}")
                print(f"frame_number: {frame_number}")
                print(f"timestamp: {updated_record[2]}")
                print(f"location: lat={updated_record[3]}, lon={updated_record[4]}")
                print(f"speed: {updated_record[5]} m/s")
                print(f"direction: {updated_record[6]}°")

                if self.unity_comm and self.unity_comm.is_connected():
                    state_mapping = {
                        'Seedling': 'Normal_Transplant',
                        'Root': 'Root_Exposure',
                        'Buried Seedling': 'Buried_Seedling'
                    }
                    state = state_mapping.get(label, label)
                    
                    self.unity_comm.send_gps_data(
                        lat=float(updated_record[3]),
                        lon=float(updated_record[4]),
                        state=state
                    )
                    print(f"send imformation=({updated_record[3]}, {updated_record[4]}), 状态={state}")
        except Exception as e:
            print(f"Error processing record: {e}")

    def monitor_file(self):
        last_position = 0
        
        while self.is_running:
            try:
                if os.path.exists('crossing_records.csv'):
                    with open('crossing_records.csv', 'r') as f:
                        f.seek(last_position)
                        reader = csv.reader(f)
                        if last_position == 0:
                            next(reader)  
                        
                        for row in reader:
                            if len(row) >= 2:  
                                try:
                                    frame_number = int(row[1])
                                    self.queue.put((str(row[0]), str(frame_number)))
                                except ValueError:
                                    print(f" {row[1]}")
                        
                        last_position = f.tell()
                        
            except Exception as e:
                print(f"Error monitoring file: {e}")
            
            time.sleep(0.1) 

    def process_queue(self):
        while self.is_running:
            try:
                label, frame_number = self.queue.get(timeout=1)
                self.process_record(label, frame_number)
                self.queue.task_done()
            except:
                continue

    def stop(self):
        self.is_running = False
        if self.unity_comm:
            self.unity_comm.stop_server()
            print("Unity communication stop")

def run_detection():
    process = subprocess.Popen(['python', 'count.py'])
    return process

def main():
    processor = RecordProcessor()
    processor.initialize_data()
    
    processor.start_unity_server()
    
    app = state_recognition.start_state_monitoring()
    
    try:
        monitor_thread = threading.Thread(target=processor.monitor_file)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        process_thread = threading.Thread(target=processor.process_queue)
        process_thread.daemon = True
        process_thread.start()
        
        detection_process = run_detection()
        
        app.root.mainloop()
        
    except KeyboardInterrupt:
    finally:
        processor.stop()
        if 'detection_process' in locals():
            detection_process.terminate()

if __name__ == "__main__":
    main() 
