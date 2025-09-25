from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QComboBox, QPushButton, QDialogButtonBox,
                             QFormLayout, QLineEdit, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QGridLayout)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
import serial.tools.list_ports

class ConnectDialog(QDialog):
    """ Dialogue pour sélectionner un port COM. """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to CAN Bus")
        layout = QVBoxLayout(self)
        
        # Création des widgets
        form_layout = QFormLayout()
        self.com_ports_combo = QComboBox()
        self.refresh_ports()
        form_layout.addRow("COM Port:", self.com_ports_combo)
        
        refresh_button = QPushButton("Refresh Ports")
        refresh_button.clicked.connect(self.refresh_ports)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addLayout(form_layout)  
        layout.addWidget(button_box)   
        layout.addWidget(refresh_button)

    def refresh_ports(self):
        self.com_ports_combo.clear()
        ports = [port.device for port in serial.tools.list_ports.comports()]
        if ports:
            self.com_ports_combo.addItems(ports)
        else:
            self.com_ports_combo.addItem("No COM ports found")

    def get_selected_port(self):
        return self.com_ports_combo.currentText()

class SettingsDialog(QDialog):
    """ Dialogue pour configurer les paramètres de connexion. """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = parent.settings if parent else {}
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.can_device_combo = QComboBox()
        self.can_device_combo.addItems(["arduino_serial", "serial"])
        
        self.com_baudrate_combo = QComboBox()
        self.com_baudrate_combo.addItems(["9600", "57600", "115200", "921600"])
        self.com_baudrate_combo.setToolTip("Only for 'arduino_serial' interface")
        
        self.can_baudrate_combo = QComboBox()
        self.can_baudrate_combo.addItems(["125 Kbit/s", "250 Kbit/s", "500 Kbit/s", "1 Mbit/s"])
        self.can_baudrate_combo.setToolTip("For native python-can interfaces")
        
        form_layout.addRow("CAN Interface:", self.can_device_combo)
        form_layout.addRow("Serial Baudrate:", self.com_baudrate_combo)
        form_layout.addRow("CAN Bitrate:", self.can_baudrate_combo)
        
        self.listen_only_check = QCheckBox("Listen Only Mode")
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addLayout(form_layout)
        layout.addWidget(self.listen_only_check)
        layout.addWidget(button_box)
        
        self.load_settings()

    def load_settings(self):
        self.can_device_combo.setCurrentText(self.settings.get("can_device", "arduino_serial"))
        self.com_baudrate_combo.setCurrentText(str(self.settings.get("com_baudrate", 115200)))
        baud_map_rev = {125000: "125 Kbit/s", 250000: "250 Kbit/s", 500000: "500 Kbit/s", 1000000: "1 Mbit/s"}
        self.can_baudrate_combo.setCurrentText(baud_map_rev.get(self.settings.get("can_baudrate", 500000)))
        self.listen_only_check.setChecked(self.settings.get("listen_only", True))

    def get_settings(self):
        can_baud_text = self.can_baudrate_combo.currentText().split()[0]
        baudrates = {"125": 125000, "250": 250000, "500": 500000, "1": 1000000}
        return {
            "can_device": self.can_device_combo.currentText(),
            "can_baudrate": baudrates.get(can_baud_text, 500000),
            "com_baudrate": int(self.com_baudrate_combo.currentText()),
            "listen_only": self.listen_only_check.isChecked()
        }

class FilterDialog(QDialog):
    """ Dialogue pour configurer les filtres de réception """
    def __init__(self, parent=None): 
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Filter")
        main_layout = QVBoxLayout(self)
        
        # --- Filtre par Masque ---
        mask_group = QGroupBox("Mask Filter")
        mask_layout = QFormLayout(mask_group)
        mask_layout.setSpacing(8)
        self.mask_mask = QLineEdit("FFFFFFFF"); self.mask_mask.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.mask_code = QLineEdit("00000000"); self.mask_code.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.enable_mask_filter = QCheckBox("Enable Mask Filter")
        mask_layout.addRow("11Bit/29Bit Mask:", self.mask_mask)
        mask_layout.addRow("11Bit/29Bit Code:", self.mask_code)
        mask_layout.addRow(self.enable_mask_filter)
        main_layout.addWidget(mask_group)

        # --- Filtre par Plage et ID discrets ---
        range_group = QGroupBox("Range Filter")
        range_layout = QGridLayout(range_group)
        self.range_start = QLineEdit("00000000"); self.range_start.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.range_end = QLineEdit("1FFFFFFF"); self.range_end.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.discrete_ids = QLineEdit(); self.discrete_ids.setPlaceholderText("Ex: 100, 1A3, 2FF")
        self.enable_range_filter = QCheckBox("Enable Range Filter")
        range_layout.addWidget(QLabel("Start ID:"), 0, 0); range_layout.addWidget(self.range_start, 0, 1)
        range_layout.addWidget(QLabel("End ID:"), 1, 0); range_layout.addWidget(self.range_end, 1, 1)
        range_layout.addWidget(QLabel("Discrete IDs:"), 2, 0); range_layout.addWidget(self.discrete_ids, 2, 1)
        range_layout.addWidget(self.enable_range_filter, 3, 0, 1, 2)
        main_layout.addWidget(range_group)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        self.load_filters()

    def load_filters(self):
        if not self.parent: return
        
        if self.parent.mask_filters:
            self.enable_mask_filter.setChecked(True)
        
        if self.parent.range_filter:
            self.range_start.setText(f"{self.parent.range_filter.get('start', 0):X}")
            self.range_end.setText(f"{self.parent.range_filter.get('end', 0x1FFFFFFF):X}")
        
        if self.parent.discrete_filters:
            self.discrete_ids.setText(", ".join([f"{fid:X}" for fid in self.parent.discrete_filters]))
            
        is_range_group_enabled = self.parent.range_filter_enabled or self.parent.discrete_filter_enabled
        self.enable_range_filter.setChecked(is_range_group_enabled)

    def get_filters(self):
        filters = {
            'mask_enabled': self.enable_mask_filter.isChecked(), 
            'mask': [],
            'range_enabled': self.enable_range_filter.isChecked(),
            'range': {},
            'discrete_enabled': self.enable_range_filter.isChecked(),
            'discrete_ids': []
        }
        
        if filters['mask_enabled']:
            try:
                user_mask = int(self.mask_mask.text(), 16)
                can_code = int(self.mask_code.text(), 16)
                actual_mask = (~user_mask) & 0x1FFFFFFF
                is_extended = len(self.mask_mask.text()) > 3 or len(self.mask_code.text()) > 3
                filters['mask'].append({"can_id": can_code, "can_mask": actual_mask, "extended": is_extended})
            except ValueError:
                filters['mask_enabled'] = False

        if filters['range_enabled']:
            try:
                start_id = int(self.range_start.text(), 16)
                end_id = int(self.range_end.text(), 16)
                filters['range'] = {'start': start_id, 'end': end_id}
            except (ValueError, TypeError):
                filters['range'] = {}

            try:
                id_text = self.discrete_ids.text()
                if id_text:
                    id_list = [int(sid.strip(), 16) for sid in id_text.split(',') if sid.strip()]
                    filters['discrete_ids'] = id_list
            except (ValueError, TypeError):
                filters['discrete_ids'] = []
        
        if not filters['range'] and not filters['discrete_ids']:
            filters['range_enabled'] = False
            filters['discrete_enabled'] = False
            
        return filters