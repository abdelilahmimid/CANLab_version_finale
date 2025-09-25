from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
import can
import time
import serial

class CanWorker(QThread):
    message_received = pyqtSignal(can.Message)
    error_occurred = pyqtSignal(str)
    connection_status = pyqtSignal(bool)

    def __init__(self, interface, channel, baudrate, com_baudrate=115200, listen_only=False, 
                 can_filters=None, range_filter=None, discrete_filter=None):
        super().__init__()
        self.mutex = QMutex()
        self._is_running = True
        self.interface = interface
        self.channel = channel      
        self.baudrate = baudrate    
        self.com_baudrate = com_baudrate 
        self.listen_only = listen_only
        self.bus = None
        
        # Initialisation directe et simplifiée des filtres avec les dictionnaires fournis par le GUI.
        self.can_filters = can_filters or []
        self.range_filter = range_filter or {}
        self.discrete_filter = discrete_filter or {}
        
        # L'état d'activation est maintenant directement lu depuis les dictionnaires
        self.is_software_filter_active = self.range_filter.get('enabled', False) or self.discrete_filter.get('enabled', False)

    def update_filters(self, can_filters=None, range_filter=None, discrete_filter=None):
        with QMutexLocker(self.mutex):
            self.can_filters = can_filters or []
            self.range_filter = range_filter or {}
            self.discrete_filter = discrete_filter or {}
            
            self.is_software_filter_active = self.range_filter.get('enabled', False) or self.discrete_filter.get('enabled', False)
            
            if self.bus and hasattr(self.bus, 'set_filters') and self.interface != "arduino_serial":
                try:
                    self.bus.set_filters(self.can_filters)
                except Exception as e:
                    print(f"Avertissement : Impossible de mettre à jour dynamiquement les filtres matériels : {e}")

    def _passes_software_filter(self, msg: can.Message):
        with QMutexLocker(self.mutex):
            if not self.is_software_filter_active:
                return True

            # La vérification de 'enabled' est la première chose à faire.
            if self.range_filter.get('enabled', False):
                if self.range_filter.get('start', 0) <= msg.arbitration_id <= self.range_filter.get('end', 0x1FFFFFFF):
                    return True # Le message passe, pas besoin de vérifier plus loin.
            
            if self.discrete_filter.get('enabled', False):
                # Utilise 'ids' pour correspondre à la structure créée dans le GUI.
                if msg.arbitration_id in self.discrete_filter.get('ids', []):
                    return True # Le message passe.
            
            return False # Le message n'a passé aucun filtre logiciel actif.

    def run(self):
        if self.interface == "arduino_serial":
            self.run_arduino_serial()
        else:
            self.run_python_can()

    def run_arduino_serial(self):
        try:
            self.bus = serial.Serial(self.channel, self.com_baudrate, timeout=0.1)
            self.connection_status.emit(True)
            while self.is_running():
                if self.bus.in_waiting > 0:
                    try:
                        line_bytes = self.bus.readline()
                        if not line_bytes: continue
                        line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                        if not line_str or line_str.startswith("---") or line_str.startswith("!!!"): continue
                        parts = line_str.split(',')
                        if len(parts) < 2: continue
                        
                        can_id_str, dlc_str = parts[0], parts[1]
                        if not can_id_str: continue

                        dlc = int(dlc_str, 16)
                        
                        if len(parts) < 2 + dlc: continue
                        data_str_list = parts[2:2+dlc]
                        
                        msg = can.Message(
                            timestamp=time.time(), arbitration_id=int(can_id_str, 16),
                            is_extended_id=len(can_id_str) > 3, dlc=dlc,
                            data=[int(d, 16) for d in data_str_list]
                        )
                        # Le filtrage logiciel est maintenant appliqué ici
                        if self._passes_software_filter(msg):
                            self.message_received.emit(msg)
                    except (ValueError, IndexError) as e:
                        print(f"Erreur de parsing série sur la ligne '{line_str}': {e}")
                else:
                    time.sleep(0.001)
        except serial.SerialException as e:
            self.error_occurred.emit(f"Erreur du port série : {e}")
        finally:
            if self.bus and self.bus.is_open: self.bus.close()
            self.connection_status.emit(False)

    def run_python_can(self):
        try:
            # Pour les interfaces natives, les filtres logiciels sont aussi appliqués.
            self.bus = can.interface.Bus(
                bustype=self.interface, channel=self.channel, bitrate=self.baudrate,
                receive_own_messages=False, can_filters=self.can_filters
            )
            self.connection_status.emit(True)
            for message in self.bus:
                if not self.is_running(): break
                if message and self._passes_software_filter(message):
                    self.message_received.emit(message)
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if self.bus: self.bus.shutdown()
            self.connection_status.emit(False)

    def stop(self):
        with QMutexLocker(self.mutex): self._is_running = False
        self.wait()

    def is_running(self):
        with QMutexLocker(self.mutex): return self._is_running

    def send_message(self, msg: can.Message):
        if not self.bus or not self.is_running():
            self.error_occurred.emit("Non connecté.")
            return False
        try:
            if self.interface == "arduino_serial":
                id_str = f"{msg.arbitration_id:X}"
                data_str = ",".join([f"{b:X}" for b in msg.data])
                command = f"S:{id_str},{msg.dlc},{data_str}\n" if data_str else f"S:{id_str},{msg.dlc}\n"
                self.bus.write(command.encode('ascii'))
            else:
                self.bus.send(msg)
            return True
        except Exception as e:
            self.error_occurred.emit(f"Échec de l'envoi : {e}")
            return False