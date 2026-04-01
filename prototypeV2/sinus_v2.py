import serial
import csv
import time
import json
import copy
import os
import numpy as np
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import datetime

## print out location
# python --> alway true
# arrduino <-- from json, manually update
# data --> where is it saving to

class Monitor:

    def __init__(self, configs):
        self.dt_s = configs["dt_s"]
        self.port = configs["port"]
        self.baudrate = configs["baudrate"]
        self.timeout = configs["timeout"]
        self.serial_conn = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
        self.save_dir = configs["save_dir"]
        self.save_filename = configs["save_filename"]
        
        self.arduino_message = ""
        self.meas_headers_init()
        self.t_s = np.array([0.0])

    def meas_headers_init(self):

        self.meas_headers = [
            "Timestamp",
            "Time (s)",
            "ENS160_R0 (Ohm)",
            "ENS160_R1 (Ohm)",
            "ENS160_R2 (Ohm)",
            "ENS160_R3 (Ohm)",
            "SGP41_VOC_R (Ohm)",
            "SGP41_NOx_R (Ohm)",   
            "TGS2602 (Ohm)",
            "SCD40 CO2 (ppm)",
            "SCD40 Temp (Celsius)",
            "SCD40 H (%RH)",
            "MQ3 (Ohm)"
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

    def write_to_csv_file(self, csv_filename=None):
        """
        This formats the data to store it locally in a csv file
        Creates a new file at midnight (00:00:00) with incremented part number
        """
        
        date_now = datetime.datetime.now()
        date_now_str = date_now.strftime("%Y-%m-%d")  # YYYY-MM-DD

        # Initialize on first call
        if not hasattr(self, 'part_number'):
            self.part_number = 1  # Start at 1
            self.initial_date = date_now_str  # Store the date when monitoring started
            self.current_date = date_now_str
        
        # Check if date has changed (crossed midnight)
        if date_now_str != self.current_date:
            # It's a new day - increment part number
            self.part_number += 1
            self.current_date = date_now_str
            print(f"\n*** Midnight passed: Creating new CSV file (part {self.part_number}) ***\n")
        
        # Determine the filename based on part number
        if self.part_number == 1:
            # First file: test_HHMMSS_YYYY-MM-DD.csv (no part number)
            csv_filename = os.path.join(self.save_dir, f"{self.save_filename}_{self.initial_date}.csv")
        else:
            # Subsequent files: test_HHMMSS_YYYY-MM-DD_pt2.csv, pt3.csv, etc.
            csv_filename = os.path.join(self.save_dir, f"{self.save_filename}_{self.initial_date}_pt{self.part_number}.csv")
        
        # Ensure directory exists
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Check if file exists
        file_exists = os.path.isfile(csv_filename)
        if not file_exists:
            print("Creating CSV:", os.path.abspath(csv_filename))
        
        # Write to CSV file
        with open(csv_filename, 'a', newline='') as output_file:
            csv_writer = csv.writer(output_file, delimiter=',')
            
            # Write headers if this is a new file
            if not file_exists:
                csv_writer.writerow(self.meas_headers)
            
            # Write the data row
            csv_writer.writerow(self.vals_row)


    def continuous_monitor(self):

        print("Begun monitoring...")

        arduino_serial = self.serial_conn
        print("Connected to arduino_port: " + self.port)
        
        message_to_arduino = "Start!"
        
        k = 0 # k is the iterator for the live monitoring
        dt_ns = self.dt_s*(10.**9) # Expressing the delay between measurements in nanoseconds to use perf_counter_ns() below
        print("dt_ns:", dt_ns, "ns")
        
        
        time.sleep(1.0)
        arduino_serial.flush()# Clearing communication buffer before sending first start signal to Arduino
        
        continue_monitoring = True
        
        date_now = datetime.datetime.now()
        
        # Generate a new file name with a timestamp
        timestamp = time.strftime("%H%M%S")
        new_filename = f"test_{timestamp}"
        #self.save_filename = new_filename
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Initialize part_number and dates
        self.part_number = 1
        self.initial_date = date_now.strftime("%Y-%m-%d")  # Date when monitoring started
        self.current_date = self.initial_date

        while continue_monitoring:
            
            # Set target time for this iteration
            target_iter_time = time.perf_counter_ns() + dt_ns
            
            if k == 0:
                self.start_time_ns = time.perf_counter_ns()
                self.t0_ns = self.start_time_ns
                self.target_time_0 = self.start_time_ns
            
            # For the first data write (k==4), reset the start time so relative time starts at 0
            if k == 4:
                self.start_time_ns = time.perf_counter_ns()
                self.target_time_0 = self.start_time_ns
            
            # Calculate relative time since start (in seconds)
            relative_time_s = (time.perf_counter_ns() - self.start_time_ns) / 1e9
            
            self.iter_time = target_iter_time - self.target_time_0
            
            message_to_arduino = ""
            message_from_arduino = ""

            print("Cycle", k + 1, "________________________")
            message_to_arduino = "!"
            arduino_serial.write(message_to_arduino.encode())

            while message_from_arduino == "" or "!" not in message_from_arduino:
                try:
                    message_from_arduino += arduino_serial.read(arduino_serial.inWaiting()).decode('utf-8')
                except UnicodeDecodeError:
                    message_from_arduino += arduino_serial.read(arduino_serial.inWaiting()).decode('utf-8')
                time.sleep(0.10)
            
            message_from_arduino = ''.join(message_from_arduino.splitlines())
            
            arduino_serial.flush()

            self.parse_meas_message(message_from_arduino, relative_time_s)
            
            # Always write data as long as we have valid data (skip first few cycles for initialization)
            if k >= 4 and len(self.vals_row) == len(self.meas_headers):
                # Use actual elapsed time for time tracking array
                actual_elapsed = (time.perf_counter_ns() - self.start_time_ns) / 1e9  # Convert ns to seconds
                t_last = np.array([actual_elapsed], dtype=np.float32)
                self.t_s = np.concatenate((self.t_s, t_last))
                
                # Write data to CSV - this handles headers automatically for new files
                self.write_to_csv_file(None)
            
            k += 1
            # Below is keeping the measurement at a constant frequency f, by waiting until 1/f seconds have passed during one iteration of the loop
            while time.perf_counter_ns() < target_iter_time:
                # Maintaining the desired measurement frequency
                continue

def main():
    
    with open("./configs_temp_v2.json", 'r') as configs_file:
        configs = json.load(configs_file)
    

    monitor = Monitor(configs)
    monitor.continuous_monitor()

if __name__ == "__main__":
    main()
    
