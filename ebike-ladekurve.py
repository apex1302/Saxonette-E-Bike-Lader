import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import csv
from datetime import datetime
import paho.mqtt.client as mqtt

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

class EbikeLoggerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("E-Bike Ladekurven Logger")
        self.root.geometry("1000x700")

        # MQTT & Logging Variablen (Voreingestellt auf dein E-Bike)
        self.broker_address = tk.StringVar(value="192.168.1.188")
        self.broker_port = tk.IntVar(value=1883)
        self.mqtt_topic = tk.StringVar(value="tele/ebike/SENSOR")  # <-- Voreingestelltes Topic
        
        self.is_logging = False
        self.csv_file = None
        self.csv_writer = None
        
        # Daten-Speicher für Plot
        self.timestamps = []
        self.power_data = []
        self.voltage_data = []
        self.current_data = []
        self.start_time = None

        self.mqtt_client = None

        # GUI Layout erstellen
        self._create_ui()

    def _create_ui(self):
        # Frame für Einstellungen
        top_frame = ttk.LabelFrame(self.root, text=" MQTT & Logging Einstellungen ", padding=10)
        top_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(top_frame, text="Broker IP:").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Entry(top_frame, textvariable=self.broker_address, width=15).grid(row=0, column=1, padx=5)

        ttk.Label(top_frame, text="Port:").grid(row=0, column=2, sticky="w", padx=5)
        ttk.Entry(top_frame, textvariable=self.broker_port, width=6).grid(row=0, column=3, padx=5)

        ttk.Label(top_frame, text="Topic:").grid(row=0, column=4, sticky="w", padx=5)
        ttk.Entry(top_frame, textvariable=self.mqtt_topic, width=25).grid(row=0, column=5, padx=5)

        self.btn_connect = ttk.Button(top_frame, text="MQTT Verbinden", command=self.toggle_mqtt)
        self.btn_connect.grid(row=0, column=6, padx=10)

        # Control Buttons
        self.btn_start = ttk.Button(top_frame, text="▶ Aufzeichnung Starten", command=self.start_logging, state="disabled")
        self.btn_start.grid(row=0, column=7, padx=5)

        self.btn_stop = ttk.Button(top_frame, text="⏹ Stoppen", command=self.stop_logging, state="disabled")
        self.btn_stop.grid(row=0, column=8, padx=5)

        # Live-Messwerte Anzeige
        val_frame = ttk.LabelFrame(self.root, text=" Aktuelle Messwerte ", padding=10)
        val_frame.pack(fill="x", padx=10, pady=5)

        self.lbl_power = ttk.Label(val_frame, text="Leistung: 0.0 W", font=("Arial", 14, "bold"))
        self.lbl_power.pack(side="left", expand=True)

        self.lbl_voltage = ttk.Label(val_frame, text="Spannung: 0 V", font=("Arial", 12))
        self.lbl_voltage.pack(side="left", expand=True)

        self.lbl_current = ttk.Label(val_frame, text="Strom: 0.0 A", font=("Arial", 12))
        self.lbl_current.pack(side="left", expand=True)

        self.lbl_status = ttk.Label(val_frame, text="Status: Nicht verbunden", font=("Arial", 10, "italic"))
        self.lbl_status.pack(side="right", padx=10)

        # Matplotlib Diagramm
        self.fig, self.ax = plt.subplots(figsize=(8, 4), dpi=100)
        self.ax.set_title("E-Bike Ladekurve (Leistung über Zeit)")
        self.ax.set_xlabel("Ladedauer (Minuten)")
        self.ax.set_ylabel("Leistung (Watt)")
        self.ax.grid(True)
        self.line, = self.ax.plot([], [], 'b-', linewidth=2, label="Leistung (W)")
        self.ax.legend(loc="upper right")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=5)

    def toggle_mqtt(self):
        if self.mqtt_client is None:
            try:
                try:
                    self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                except AttributeError:
                    self.mqtt_client = mqtt.Client()

                self.mqtt_client.on_connect = self.on_connect
                self.mqtt_client.on_message = self.on_message
                self.mqtt_client.connect(self.broker_address.get(), self.broker_port.get(), 60)
                self.mqtt_client.loop_start()

                self.btn_connect.config(text="Trennen")
                self.lbl_status.config(text="Verbunden mit MQTT", foreground="black")
                self.btn_start.config(state="normal")
            except Exception as e:
                messagebox.showerror("Fehler", f"MQTT Verbindung fehlgeschlagen:\n{e}")
                self.mqtt_client = None
        else:
            self._disconnect_mqtt()

    def _disconnect_mqtt(self):
        if self.mqtt_client:
            self.stop_logging()
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
            self.btn_connect.config(text="MQTT Verbinden")
            self.lbl_status.config(text="Getrennt", foreground="black")
            self.btn_start.config(state="disabled")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        topic = self.mqtt_topic.get()
        client.subscribe(topic)

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # Tasmota JSON-Struktur parsen
            energy = None
            if "ENERGY" in payload:
                energy = payload["ENERGY"]
            elif "sn" in payload and "ENERGY" in payload["sn"]:
                energy = payload["sn"]["ENERGY"]

            if energy:
                power = float(energy.get("Power", 0.0))
                voltage = float(energy.get("Voltage", 0))
                current = float(energy.get("Current", 0.0))
                timestamp = datetime.now()

                # GUI im Haupt-Thread aktualisieren
                self.root.after(0, self.process_new_data, timestamp, power, voltage, current)
        except Exception:
            pass

    def process_new_data(self, timestamp, power, voltage, current):
        self.lbl_power.config(text=f"Leistung: {power:.1f} W")
        self.lbl_voltage.config(text=f"Spannung: {voltage:.0f} V")
        self.lbl_current.config(text=f"Strom: {current:.2f} A")

        if self.is_logging:
            if self.start_time is None:
                self.start_time = timestamp

            elapsed_minutes = (timestamp - self.start_time).total_seconds() / 60.0

            self.timestamps.append(elapsed_minutes)
            self.power_data.append(power)
            self.voltage_data.append(voltage)
            self.current_data.append(current)

            if self.csv_writer:
                self.csv_writer.writerow([
                    timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{elapsed_minutes:.2f}",
                    power,
                    voltage,
                    current
                ])
                self.csv_file.flush()

            self.line.set_data(self.timestamps, self.power_data)
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw()

    def start_logging(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Dateien", "*.csv")],
            initialfile=f"ebike_ladekurve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not filename:
            return

        self.timestamps.clear()
        self.power_data.clear()
        self.voltage_data.clear()
        self.current_data.clear()
        self.start_time = None

        self.csv_file = open(filename, mode="w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file, delimiter=";")
        self.csv_writer.writerow(["Zeitstempel", "Ladedauer_Minuten", "Leistung_W", "Spannung_V", "Strom_A"])

        self.is_logging = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="Aufzeichnung läuft...", foreground="green")

    def stop_logging(self):
        if self.is_logging:
            self.is_logging = False
            if self.csv_file:
                try:
                    self.csv_file.close()
                except Exception:
                    pass
                self.csv_file = None
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.lbl_status.config(text="Aufzeichnung beendet", foreground="black")

    def on_close(self):
        """Sauberes Beenden aller Prozesse"""
        self.stop_logging()
        self._disconnect_mqtt()
        plt.close('all')  # Matplotlib Ressourcen freigeben
        self.root.quit()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = EbikeLoggerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()