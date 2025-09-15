import math
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
import os
import time
import threading
import unity_communication 

def latlon_to_xy(lat, lon, ref_lat=24.64):
    meters_per_deg_lat = 111000  # 1kat ≈ 111km
    meters_per_deg_lon = 111000 * math.cos(math.radians(ref_lat))  
    x = lon * meters_per_deg_lon
    y = lat * meters_per_deg_lat
    return x, y

def euclidean_distance(lat1, lon1, lat2, lon2, ref_lat=24.64):
    x1, y1 = latlon_to_xy(lat1, lon1, ref_lat)
    x2, y2 = latlon_to_xy(lat2, lon2, ref_lat)
    distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    return distance

# status 
def classify_planting_status(seedlings, standard_spacing):
    S = standard_spacing 
    S_min = 0.4 * S     
    S_max = 1.6 * S     
    
    statuses = {}        
    counts = {           
        "Normal": 0,
        "Root Exposed": 0,
        "Buried": 0,
        "Overlap": 0,    
        "Missing": 0
    }
    missed_points = []   
    overlap_group = []   
    
    unique_seedlings = []
    seen_coords = set()
    for s in seedlings:
        coord = (s["lat"], s["lon"])
        if coord not in seen_coords:
            seen_coords.add(coord)
            unique_seedlings.append(s)
    
    # deal with first seedling
    if unique_seedlings:
        frame_id = f"seedling_{unique_seedlings[0]['frame']}"
        if unique_seedlings[0]["label"] == "Seedling":
            statuses[frame_id] = "Normal"
            counts["Normal"] += 1
        elif unique_seedlings[0]["label"] == "Root":
            statuses[frame_id] = "Root Exposed"
            counts["Root Exposed"] += 1
        elif unique_seedlings[0]["label"] == "Buried Seedling":
            statuses[frame_id] = "Buried"
            counts["Buried"] += 1
    
    # check in list
    for i in range(1, len(unique_seedlings)):
        seedling_id = f"seedling_{unique_seedlings[i]['frame']}"
        current = unique_seedlings[i]
        previous = unique_seedlings[i-1]
        distance = euclidean_distance(current["lat"], current["lon"], previous["lat"], previous["lon"])
      
        if distance < S_min:
            if not overlap_group or overlap_group[-1][-1] == previous["frame"]:
                if not overlap_group:
                    overlap_group.append([previous["frame"], current["frame"]])
                else:
                    overlap_group[-1].append(current["frame"])
            else:
                overlap_group.append([previous["frame"], current["frame"]])
            statuses[f"seedling_{previous['frame']}"] = "Overlap"
            statuses[seedling_id] = "Overlap"
            if statuses[f"seedling_{previous['frame']}"] != "Overlap": 
                if unique_seedlings[i-1]["label"] == "Seedling":
                    counts["Normal"] -= 1
                elif unique_seedlings[i-1]["label"] == "Root":
                    counts["Root Exposed"] -= 1
                elif unique_seedlings[i-1]["label"] == "Buried Seedling":
                    counts["Buried"] -= 1
        else:
            if overlap_group:
                counts["Overlap"] += 1
                overlap_group = []
            
            if distance > S_max:
                mid_lat = (current["lat"] + previous["lat"]) / 2
                mid_lon = (current["lon"] + previous["lon"]) / 2
                missed_points.append({
                    "lat": mid_lat,
                    "lon": mid_lon,
                    "frame_prev": previous["frame"],
                    "frame_curr": current["frame"]
                })
                counts["Missing"] += 1
                if current["label"] == "Seedling":
                    statuses[seedling_id] = "Normal"
                    counts["Normal"] += 1
                elif current["label"] == "Root":
                    statuses[seedling_id] = "Root Exposed"
                    counts["Root Exposed"] += 1
                elif current["label"] == "Buried Seedling":
                    statuses[seedling_id] = "Buried"
                    counts["Buried"] += 1
            else:
                if current["label"] == "Seedling":
                    statuses[seedling_id] = "Normal"
                    counts["Normal"] += 1
                elif current["label"] == "Root":
                    statuses[seedling_id] = "Root Exposed"
                    counts["Root Exposed"] += 1
                elif current["label"] == "Buried Seedling":
                    statuses[seedling_id] = "Buried"
                    counts["Buried"] += 1
    
    if overlap_group:
        counts["Overlap"] += 1
      
    if len(unique_seedlings) > 1 and statuses.get(f"seedling_{unique_seedlings[0]['frame']}") != "Overlap":
        distance = euclidean_distance(unique_seedlings[0]["lat"], unique_seedlings[0]["lon"], 
                                     unique_seedlings[1]["lat"], unique_seedlings[1]["lon"])
        if distance < S_min:
            statuses[f"seedling_{unique_seedlings[0]['frame']}"] = "Overlap"
            if overlap_group and overlap_group[0][0] == unique_seedlings[1]["frame"]:
                overlap_group[0].insert(0, unique_seedlings[0]["frame"])
            else:
                counts["Overlap"] += 1
                overlap_group.insert(0, [unique_seedlings[0]["frame"], unique_seedlings[1]["frame"]])
            if unique_seedlings[0]["label"] == "Seedling":
                counts["Normal"] -= 1
            elif unique_seedlings[0]["label"] == "Root":
                counts["Root Exposed"] -= 1
            elif unique_seedlings[0]["label"] == "Buried Seedling":
                counts["Buried"] -= 1
    
    return statuses, counts, missed_points

def process_csv(file_path):
    df = pd.read_csv(file_path)
    seedlings = []
    for _, row in df.iterrows():
        seedlings.append({
            "label": row["Label"],  # 支持Seedling, Root, Buried Seedling
            "frame": row["Frame_Number"],
            "lat": float(row["Latitude"]),
            "lon": float(row["Longitude"])
        })
    return seedlings

class PlantingStatusApp:
    def __init__(self, file_path="crossing_records.csv", standard_spacing=0.5, unity_comm=None):
        self.file_path = file_path
        self.standard_spacing = standard_spacing
        self.last_modification_time = 0
        self.seedlings = []
        self.statuses = {}
        self.counts = {}
        self.missed_points = []
        self.is_running = True
        self.lock = threading.Lock()
        
        # Unity Communication
        self.unity_comm = unity_comm
        
        self.xlim = None
        self.ylim = None
        
        self.root = tk.Tk()
        self.root.geometry("1200x800")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.create_widgets()
        
        self.monitor_thread = threading.Thread(target=self.monitor_file)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def create_widgets(self):
        self.fig = Figure(figsize=(12, 8), dpi=100)

        gs = gridspec.GridSpec(1, 2, width_ratios=[4, 1], figure=self.fig)
        self.scatter_ax = self.fig.add_subplot(gs[0])
        self.stats_ax = self.fig.add_subplot(gs[1])

        self.stats_ax.axis('off')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.update_stats_display()
    
    def update_stats_display(self):
        self.stats_ax.clear()
        self.stats_ax.axis('off')
        
        self.stats_ax.text(0.5, 0.95, "Status Statistics", 
                         fontsize=14, fontweight='bold', 
                         ha='center', va='top')
        
        statuses = ["Normal", "Root Exposed", "Buried", "Overlap", "Missing"]
        colors = {
            "Normal": "green",
            "Root Exposed": "red",
            "Buried": "blue",
            "Overlap": "orange",
            "Missing": "purple"
        }
        
        y_pos = 0.85
        for status in statuses:
            count = self.counts.get(status, 0)
            self.stats_ax.text(0.5, y_pos, f"{status}: {count}", 
                             fontsize=12, ha='center', va='top',
                             bbox=dict(facecolor='white', edgecolor=colors.get(status, 'black'), 
                                       alpha=0.8, boxstyle='round,pad=0.5'))
            y_pos -= 0.1
    
    def update_scatter_plot(self):
        self.scatter_ax.clear()
        
        colors = {
            "Normal": "green",
            "Root Exposed": "red",
            "Buried": "blue",
            "Overlap": "orange"
        }
        
        added_labels = set()
        
        overlap_centers = {}  # {group_first_frame: (lat_avg, lon_avg)}
        overlap_group = []
        
        for i in range(len(self.seedlings)):
            current = self.seedlings[i]
            frame_id = f"seedling_{current['frame']}"
            status = self.statuses.get(frame_id, "Normal")
            
            if status == "Overlap":
                if not overlap_group or overlap_group[-1]["frame"] == self.seedlings[i-1]["frame"]:
                    overlap_group.append(current)
                else:
                    if overlap_group:
                        avg_lat = sum(s["lat"] for s in overlap_group) / len(overlap_group)
                        avg_lon = sum(s["lon"] for s in overlap_group) / len(overlap_group)
                        overlap_centers[overlap_group[0]["frame"]] = (avg_lat, avg_lon)
                        overlap_group = [current]
            else:
                if overlap_group:
                    avg_lat = sum(s["lat"] for s in overlap_group) / len(overlap_group)
                    avg_lon = sum(s["lon"] for s in overlap_group) / len(overlap_group)
                    overlap_centers[overlap_group[0]["frame"]] = (avg_lat, avg_lon)
                    overlap_group = []

        if overlap_group:
            avg_lat = sum(s["lat"] for s in overlap_group) / len(overlap_group)
            avg_lon = sum(s["lon"] for s in overlap_group) / len(overlap_group)
            overlap_centers[overlap_group[0]["frame"]] = (avg_lat, avg_lon)
        
        for seedling in self.seedlings:
            frame_id = f"seedling_{seedling['frame']}"
            status = self.statuses.get(frame_id, "Normal")
            
            if status == "Overlap":
                if seedling["frame"] not in overlap_centers:
                    continue
                lat, lon = overlap_centers[seedling["frame"]]
            else:
                lat, lon = seedling["lat"], seedling["lon"]
            
            color = colors.get(status, "gray")

            label = status if status not in added_labels else ""
            if label:
                added_labels.add(status)
                
            self.scatter_ax.scatter(lon, lat, 
                                   c=color, marker="o", s=100, 
                                   label=label)

        if self.missed_points:
            missed_lats = [point["lat"] for point in self.missed_points]
            missed_lons = [point["lon"] for point in self.missed_points]
            self.scatter_ax.scatter(missed_lons, missed_lats, 
                                   facecolors='none', 
                                   edgecolors='purple', 
                                   linewidth=2, 
                                   s=150, 
                                   marker="o", 
                                   label="Missing" if "Missing" not in added_labels else "")

        if self.xlim and self.ylim:
            self.scatter_ax.set_xlim(self.xlim)
            self.scatter_ax.set_ylim(self.ylim)

        self.scatter_ax.legend(loc='best')
        self.scatter_ax.set_xlabel("Longitude")
        self.scatter_ax.set_ylabel("Latitude")
        self.scatter_ax.set_title("Planting Status Distribution")
        
        self.fig.tight_layout()
    
    def update_display(self):
        try:
            with self.lock:
                self.update_scatter_plot()
                self.update_stats_display()
            
            # Refresh canva
            self.canvas.draw_idle()  
            
        except Exception as e:
            print(f"ERROR: {e}")
    
    def update_limits(self):
        if not self.seedlings:
            return
            
        lons = [s["lon"] for s in self.seedlings]
        lats = [s["lat"] for s in self.seedlings]
        
        if self.missed_points:
            lons.extend([p["lon"] for p in self.missed_points])
            lats.extend([p["lat"] for p in self.missed_points])
            
        xmin, xmax = min(lons), max(lons)
        ymin, ymax = min(lats), max(lats)
        
        if xmax - xmin < 1e-5:
            xmin -= 0.0001
            xmax += 0.0001
        if ymax - ymin < 1e-5:
            ymin -= 0.0001
            ymax += 0.0001
            
        padding_x = (xmax - xmin) * 0.1
        padding_y = (ymax - ymin) * 0.1
        new_xlim = (xmin - padding_x, xmax + padding_x)
        new_ylim = (ymin - padding_y, ymax + padding_y)

        if self.xlim is None:
            self.xlim = new_xlim
            self.ylim = new_ylim
            return

        current_width = self.xlim[1] - self.xlim[0]
        current_height = self.ylim[1] - self.ylim[0]
        margin_x = current_width * 0.1
        margin_y = current_height * 0.1
        
        need_update = False
        if xmin < self.xlim[0] + margin_x or xmax > self.xlim[1] - margin_x:
            self.xlim = new_xlim
            need_update = True
        if ymin < self.ylim[0] + margin_y or ymax > self.ylim[1] - margin_y:
            self.ylim = new_ylim
            need_update = True
            
        return need_update
    
    def monitor_file(self):
        last_content = ""
        while self.is_running:
            try:
                if os.path.exists(self.file_path):
                    with open(self.file_path, 'r') as f:
                        current_content = f.read()

                    if current_content != last_content:
                        last_content = current_content  
                  
                        with self.lock:
                            self.seedlings = process_csv(self.file_path)
                            self.statuses, self.counts, self.missed_points = classify_planting_status(
                                self.seedlings, self.standard_spacing)
                            
                            need_update = self.update_limits()
                        
                        print("\n new data:")
                        for key, value in self.counts.items():
                            print(f"{key}: {value}")
                        
                        self.root.after(0, self.update_display)
            except Exception as e:
                print(f"ERROR: {e}")
            
            time.sleep(0.1)  
    
    def on_closing(self):
        self.is_running = False
        
        try:
            plt.figure(figsize=(12, 8))
            colors = {
                "Normal": "green",
                "Root Exposed": "red",
                "Buried": "blue",
                "Overlap": "orange"
            }
            
            added_labels = set()
            
            for seedling in self.seedlings:
                frame_id = f"seedling_{seedling['frame']}"
                status = self.statuses.get(frame_id, "Normal")
                color = colors.get(status, "gray")
                
                label = status if status not in added_labels else ""
                if label:
                    added_labels.add(status)
                    
                plt.scatter(seedling["lon"], seedling["lat"], 
                          c=color, marker="o", s=100, 
                          label=label)
            
            if self.missed_points:
                missed_lats = [point["lat"] for point in self.missed_points]
                missed_lons = [point["lon"] for point in self.missed_points]
                plt.scatter(missed_lons, missed_lats, 
                          facecolors='none', 
                          edgecolors='purple', 
                          linewidth=2, 
                          s=150, 
                          marker="o", 
                          label="Missing" if "Missing" not in added_labels else "")
            
            plt.legend(loc='best')
            plt.xlabel("Longitude")
            plt.ylabel("Latitude")
            plt.title("Planting Status Distribution")
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"planting_status_{timestamp}.png"
            
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            print(f"sava as: {filename}")
            plt.close()
        except Exception as e:
            print(f"ERROR: {e}")
        
        self.root.destroy()
    
    def start(self):
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self.monitor_file)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def stop(self):
        self.is_running = False
        self.root.quit()

def start_state_monitoring(file_path="crossing_records.csv", standard_spacing=0.5, unity_comm=None):
    app = PlantingStatusApp(file_path, standard_spacing, unity_comm)
    app.start()
    return app

if __name__ == "__main__":
    unity_comm = unity_communication.UnityCommManager(host='127.0.0.1', port=8888)
    unity_comm.start_server()
    
    app = start_state_monitoring(unity_comm=unity_comm)
    app.root.mainloop()  #  Run GUI
