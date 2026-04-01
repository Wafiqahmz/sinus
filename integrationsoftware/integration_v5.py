import serial
import csv
import time
import copy
import os
import numpy as np
import datetime
import json
import tkinter as tk
from tkinter import messagebox
import threading
import pandas as pd
import joblib
from sklearn.base import BaseEstimator, TransformerMixin

DURATION = 120
TIME_BEFORE_BLOW = 25 #s
MODEL_PATH = "abrs_classifier.pkl"

class RowPatternFill(BaseEstimator, TransformerMixin):
    def __init__(self, starts=range(0,9), step=9):
        self.starts = starts
        self.step = step

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        X_filled = pd.DataFrame(X).copy()

        for start in self.starts:
            cols = X_filled.columns[start::self.step]
            X_filled.loc[:, cols] = X_filled.loc[:, cols].bfill(axis=1).ffill(axis=1)

        return X_filled

classifier = joblib.load(MODEL_PATH)

class Monitor:
    def __init__(self, configs):
        self.dt_s = configs["dt_s"]
        self.port = configs["port"]
        self.baudrate = configs["baudrate"]
        self.timeout = configs["timeout"]
        self.save_dir = configs["save_dir"]
        self.save_filename = configs.get("save_filename", "abrs_run")

        self.serial_conn = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout
        )

        time.sleep(2)  # allow Arduino to reset after serial opens
        self.serial_conn.reset_input_buffer()
        self.serial_conn.reset_output_buffer()

        self.arduino_message = ""
        self.t_s = np.array([0.0])
        self.meas_headers_init()

    def meas_headers_init(self):
        self.meas_headers = [
            "Timestamp",
            "Time_s",
            "ENS160_R0",
            "ENS160_R1",
            "ENS160_R2",
            "ENS160_R3",
            "SGP41_VOC_R",
            "SGP41_NOx_R",
            "TGS2602",
            "SCD40_CO2",
            "SCD40_T",
            "SCD40_H",
            "MQ3_R"
        ]

        self.meas_sensors = [
            "System",
            "System",
            "ENS160",
            "ENS160",
            "ENS160",
            "ENS160",
            "SGP41",
            "SGP41",
            "TGS2602",
            "SCD40",
            "SCD40",
            "SCD40",
            "MQ3"
        ]

    def is_float(self, string):
        try:
            float(string)
            return True
        except ValueError:
            return False

    def parse_meas_message(self, arduino_message, relative_time_s):
        """
        This function receives the string of sensor data sent by the Arduino, and parses the string extracting sensor outputs
        """

        arduino_message = arduino_message[1:-2]
        message_split = arduino_message.split(',')
        
        vals_row = copy.deepcopy(message_split)

        for i, val in enumerate(message_split):
            if val.isnumeric() or self.is_float(val):
                vals_row[i] = str(val).strip()
            else:
                vals_row[i] = "-"
        
        # Get absolute timestamp with full date and time
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]
        # Get relative time with 2 decimal places 
        time_value = f"{relative_time_s:.2f}"
        
        # Prepend both timestamp and relative time
        vals_row.insert(0, time_value)
        vals_row.insert(0, timestamp)

        self.vals_row = vals_row
        return vals_row

    def create_run_filename(self, prefix=None):
        """
        Create one filename for one full ABRS run.
        """
        os.makedirs(self.save_dir, exist_ok=True)

        if prefix is None:
            prefix = self.save_filename

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = os.path.join(self.save_dir, f"{prefix}_{timestamp}.csv")
        return csv_filename

    def initialize_csv(self, csv_filename):
        """
        Create a new CSV and write the header once.
        """
        os.makedirs(self.save_dir, exist_ok=True)

        with open(csv_filename, "w", newline="") as output_file:
            csv_writer = csv.writer(output_file, delimiter=",")
            csv_writer.writerow(self.meas_headers)

    def write_row_to_csv(self, csv_filename, vals_row):
        """
        Append one parsed measurement row to the CSV.
        """
        with open(csv_filename, "a", newline="") as output_file:
            csv_writer = csv.writer(output_file, delimiter=",")
            csv_writer.writerow(vals_row)

    def read_arduino_message(self):
        """
        Request one measurement from Arduino and return the raw message.
        Assumes Arduino responds to '!' with one full sensor line.
        """
        arduino_serial = self.serial_conn

        # request measurement
        arduino_serial.write(b"!")

        # read until message terminator
        message = arduino_serial.read_until(b'!').decode("utf-8", errors="ignore")

        return message

    def collect_data(self, duration_s, csv_filename=None):
        """
        Collect data for a fixed duration and save to one CSV file.

        Returns:
            csv_filename (str): path to saved CSV
        """
        print("Begun monitoring...")
        print("Connected to arduino_port:", self.port)

        arduino_serial = self.serial_conn
        dt_ns = int(self.dt_s * 1e9)

        time.sleep(1.0)
        arduino_serial.flush()

        if csv_filename is None:
            csv_filename = self.create_run_filename()

        self.initialize_csv(csv_filename)

        start_time_ns = time.perf_counter_ns()
        k = 0

        while True:
            loop_start_ns = time.perf_counter_ns()
            relative_time_s = (loop_start_ns - start_time_ns) / 1e9

            if relative_time_s >= duration_s:
                break

            print(f"Cycle {k + 1} ________________________")

            raw_message = self.read_arduino_message()
            vals_row = self.parse_meas_message(raw_message, relative_time_s)

            if len(vals_row) == len(self.meas_headers):
                self.write_row_to_csv(csv_filename, vals_row)

                t_last = np.array([relative_time_s], dtype=np.float32)
                self.t_s = np.concatenate((self.t_s, t_last))
            else:
                print("Warning: skipped malformed row")
                print("Row length:", len(vals_row))
                print("Expected :", len(self.meas_headers))

            k += 1

            target_iter_time = loop_start_ns + dt_ns
            while time.perf_counter_ns() < target_iter_time:
                continue

        print("Finished monitoring.")
        print("Saved CSV:", csv_filename)
        return csv_filename

    def close(self):
        """
        Close serial connection safely.
        """
        if hasattr(self, "serial_conn") and self.serial_conn.is_open:
            self.serial_conn.close()
            print("Serial connection closed.")

class GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ABRS Diagnostic Tool")
        self.root.geometry("400x220")

        self.is_running = False
        self.monitor = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.title_label = tk.Label(
            root,
            text="ABRS Diagnostic Tool",
            font=("Arial", 16, "bold")
        )
        self.title_label.pack(pady=(20, 10))

        self.status_var = tk.StringVar(value="Status: Ready")
        self.status_label = tk.Label(
            root,
            textvariable=self.status_var,
            font=("Arial", 12)
        )
        self.status_label.pack(pady=10)

        self.result_label = tk.Label(
            root,
            text="Prediction: -",
            font=("Arial", 12),
            justify="center"
        )
        self.result_label.pack(pady=10)

        self.run_button = tk.Button(
            root,
            text="Run",
            font=("Arial", 14),
            width=12,
            height=2,
            command=self.start_run
        )
        self.run_button.pack(pady=20)
    
    def safe_shutdown_monitor(self):
        if self.monitor is not None:
            try:
                self.monitor.serial_conn.write(b'0')   # turn fan OFF
                self.monitor.serial_conn.flush()
                time.sleep(0.5)
            except Exception:
                pass

            try:
                self.monitor.close()
            except Exception:
                pass

            self.monitor = None
    
    def on_close(self):
        self.safe_shutdown_monitor()
        self.root.destroy()
    
    def blow_into_device(self):
        try:
            self.root.after(0, self.root.bell)
        except Exception:
            pass

        self.root.after(0, lambda: messagebox.showinfo("Prompt", "Blow into device"))
    
    def start_run(self):
        if self.is_running:
            return

        self.is_running = True
        self.run_button.config(state="disabled")
        self.status_var.set("Status: Running...")

        worker = threading.Thread(target=self.run_protocol, daemon=True)
        worker.start()

    def run_protocol(self):
        try:
            with open("configs_temp_v2.json", "r") as f:
                configs = json.load(f)

            self.monitor = Monitor(configs)

            # turn fan ON
            self.monitor.serial_conn.write(b'1')
            self.monitor.serial_conn.flush()
            time.sleep(1.0)
            
            # start separate 30 s prompt timer
            prompt_timer = threading.Timer(TIME_BEFORE_BLOW, self.blow_into_device)
            prompt_timer.start()

            # collect sensor data
            csv_path = self.monitor.collect_data(duration_s=DURATION)

            # preprocess data
            features = preprocess_run(csv_path)
            print("Feature shape:", features.shape)
            print("First features:", features.iloc[0, :10].to_list())

            # run classifier
            self.predict_current_sample(csv_path)

            self.root.after(0, lambda: self.status_var.set("Status: Finished"))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self.status_var.set("Status: Error"))

        finally:
            try:
                prompt_timer.cancel()
            except Exception:
                pass

            self.safe_shutdown_monitor()
            self.root.after(0, lambda: self.run_button.config(state="normal"))
            self.is_running = False
    
    def predict_current_sample(self, csv_path):
        try:
            # preprocess current run into 1-row dataframe
            X_new = preprocess_run(csv_path)

            # final class prediction: 0 or 1
            pred = classifier.predict(X_new)[0]

            # probability output
            probs = classifier.predict_proba(X_new)[0]
            prob_healthy = probs[0]
            prob_abrs = probs[1]

            # choose label
            if pred == 1:
                pred_text = "ABRS"
                pred_prob = prob_abrs
            else:
                pred_text = "Healthy"
                pred_prob = prob_healthy

            output_text = (
                f"Prediction: {pred_text}\n"
                f"P(Healthy): {prob_healthy:.3f}\n"
                f"P(Unhealthy): {prob_abrs:.3f}\n"
                f"Final confidence: {pred_prob:.3f}"
            )

            self.result_label.config(text=output_text)

        except Exception as e:
            self.result_label.config(text=f"Prediction failed:\n{e}")

def preprocess_run(csv_path):

    df = pd.read_csv(csv_path, na_values="-")

    # Remove unused columns
    df = df.drop(columns=["Timestamp","ENS160_R1","SGP41_NOx_R"], errors="ignore")

    # Convert resistance → response, S = Rmax/R - 1
    sensor_cols = df.columns
    df_s = pd.DataFrame()

    for col in sensor_cols:
        if col == "Time_s":
            continue

        r = df[col].astype(float)
        r_max = r.max()

        df_s[col.replace("_R", "_S")] = np.where(
            r != 0,
            r_max / r - 1,
            np.nan
        )

    # Remove Time column completely
    if "Time_s" in df_s.columns:
        df_s = df_s.drop(columns=["Time_s"])

    # Flatten time series
    feature_vector = df_s.to_numpy().flatten()

    return pd.DataFrame([feature_vector])

if __name__ == "__main__":
    root = tk.Tk()
    app = GUI(root)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.safe_shutdown_monitor()
    