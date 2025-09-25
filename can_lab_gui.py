import sys, csv, time
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMenuBar, QMenu, QFileDialog,
                             QMessageBox, QLineEdit, QPushButton, QCheckBox,
                             QSplitter, QStatusBar, QLabel, QGroupBox, QGridLayout, QComboBox)
from PyQt6.QtCore import Qt, QTimer, QRegularExpression
from PyQt6.QtGui import QAction, QIntValidator, QRegularExpressionValidator , QBrush, QColor
from can_worker import CanWorker
from dialogs import ConnectDialog, SettingsDialog, FilterDialog
import can

# --- DBC ---
from dbc_manager import DBCManager

class NumericTableWidgetItem(QTableWidgetItem):
    """ Widget d'item de tableau pour permettre un tri numérique correct. """
    def __lt__(self, other):
        try: return float(self.text()) < float(other.text())
        except (ValueError, TypeError): return super().__lt__(other)

class SelectAllLineEdit(QLineEdit):
    """ QLineEdit qui sélectionne tout son contenu lorsqu'il reçoit le focus. """
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

STYLESHEET = """
QWidget { font-family: Arial; } 
QGroupBox { background-color: #F0F0F0; border: 1px solid #BDBDBD; border-radius: 5px; margin-top: 1ex; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; font-weight: bold; } 
#TransmitEditPanel { background-color: #ECECEC; border-radius: 4px; border: 1px solid #BDBDBD; }
QPushButton { background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #F6F6F6, stop: 1 #E0E0E0); border: 1px solid #888888; border-radius: 3px; min-height: 23px; min-width: 75px; padding: 2px 10px; }
QPushButton:hover { background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #EAF6FF, stop: 1 #D9F0FF); border-color: #0078D7; } 
QPushButton:pressed { background-color: #D9D9D9; border-style: inset; }
QLineEdit, QComboBox { background-color: white; border: 1px solid #ACACAC; border-radius: 2px; min-height: 21px; } 
QLineEdit:disabled { background-color: #F0F0F0; }
QStatusBar::item { border: none; }
"""

class CanLabGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CANLab-V1.00.00"); self.setGeometry(100, 100, 1200, 800); self.setStyleSheet(STYLESHEET)
        
        self.TX_MODE_ROLE = Qt.ItemDataRole.UserRole
        self.TRIGGER_ID_ROLE = Qt.ItemDataRole.UserRole + 1

        # --- DBC ---
        self.dbc_manager = DBCManager()

        self.can_worker = None; self.is_monitoring = True
        self.settings = {"can_device": "arduino_serial", "can_baudrate": 500000, "com_baudrate": 921600, "listen_only": True}
        self.can_filters = []; 
        self.tx_periodic_timers = {}; self.start_time = 0
        self.monitor_data_cache = {}; self.tracer_data_cache = [] 
        self.monitor_id_to_row = {} 
        self.trace_save_file = None; self.trace_save_buffer = []; self.tx_save_file = None; self.tx_save_buffer = []
        self.save_timer = QTimer(self); self.save_timer.timeout.connect(self._flush_save_buffers)
        
        self.mask_filters = []
        self.range_filter = {}
        self.range_filter_enabled = False
        self.discrete_filters = []          
        self.discrete_filter_enabled = False 
        
        self._create_actions(); self._create_menu_bar(); self._create_central_widget(); self._create_status_bar()
        self.connection_check_timer = QTimer(self); self.connection_check_timer.timeout.connect(self.check_connection_status); self.connection_check_timer.start(2000)

    def _create_actions(self):
        self.actions = { 
            "connect": QAction("Connect", self), "reset": QAction("Reset", self), "settings": QAction("Settings", self), 
            "filter": QAction("Filter", self), "quit": QAction("Quit", self),
            "save_rx_tracer": QAction("Save Rx Tracer", self), "save_rx_monitor": QAction("Save Rx Monitor", self), 
            "load_tx_list": QAction("Load Tx List", self), "save_tx_list": QAction("Save Tx List", self),
            "load_dbc_file": QAction("Load DBC File", self),
            "load_dbc_folder": QAction("Load DBC Folder", self),
        }
        self.actions["trace_monitor"] = QAction("Monitor", self, checkable=True); self.actions["trace_monitor"].setChecked(True)
        self.actions["connect"].triggered.connect(self.show_connect_dialog); self.actions["reset"].triggered.connect(self.reset_all)
        self.actions["settings"].triggered.connect(self.show_settings_dialog); self.actions["filter"].triggered.connect(self.show_filter_dialog)
        self.actions["trace_monitor"].triggered.connect(self.toggle_receive_mode); self.actions["quit"].triggered.connect(self.close)
        self.actions["save_rx_tracer"].triggered.connect(self.save_rx_tracer_data); self.actions["save_rx_monitor"].triggered.connect(self.save_rx_monitor_data)
        self.actions["load_tx_list"].triggered.connect(self.load_tx_list); self.actions["save_tx_list"].triggered.connect(self.save_tx_list)
        self.actions["load_dbc_file"].triggered.connect(self._handle_load_dbc_file)
        self.actions["load_dbc_folder"].triggered.connect(self._handle_load_dbc_folder)

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        
        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.actions["save_rx_tracer"])
        file_menu.addAction(self.actions["save_rx_monitor"])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["load_tx_list"])
        file_menu.addAction(self.actions["save_tx_list"])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["quit"])
        
        dbc_menu = menu_bar.addMenu("DBC")
        dbc_menu.addAction(self.actions["load_dbc_file"])
        dbc_menu.addAction(self.actions["load_dbc_folder"])
        
        menu_bar.addAction(self.actions["connect"])
        menu_bar.addAction(self.actions["reset"])
        menu_bar.addAction(self.actions["settings"])
        menu_bar.addAction(self.actions["filter"])
        menu_bar.addAction(self.actions["trace_monitor"])

    def _create_central_widget(self):
        splitter = QSplitter(Qt.Orientation.Vertical); splitter.addWidget(self._create_receive_panel()); splitter.addWidget(self._create_transmit_panel())
        splitter.setSizes([500, 300]); self.setCentralWidget(splitter)

    def _create_receive_panel(self):
        self.rx_group = QGroupBox(); layout = QVBoxLayout(self.rx_group); self.rx_table = QTableWidget()
        self.rx_table.setSortingEnabled(True); self.rx_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rx_table.doubleClicked.connect(self.copy_rx_to_tx_form)
        self.rx_table.itemChanged.connect(self._on_rx_comment_changed)
        self.rx_table.setAlternatingRowColors(True)
        layout.addWidget(self.rx_table); self._setup_receive_table()
        return self.rx_group

    def _setup_receive_table(self):
        self.rx_table.setSortingEnabled(False); self.rx_table.clear(); self.rx_table.setRowCount(0); header = self.rx_table.horizontalHeader()
        if self.is_monitoring:
            self.rx_group.setTitle("Receive (Monitor)")
            self.rx_table.setColumnCount(6)
            self.rx_table.setHorizontalHeaderLabels(["ID", "DLC", "Data", "Period", "Count", "Comment / Message Name"])
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive); self.rx_table.setColumnWidth(0,   90); self.rx_table.setColumnWidth(1, 90); self.rx_table.setColumnWidth(2, 340); self.rx_table.setColumnWidth(3, 100); self.rx_table.setColumnWidth(4, 100); 
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            self.rx_table.itemDoubleClicked.connect(self._edit_rx_comment)
        else:
            self.rx_group.setTitle("Receive (Tracer)")
            self.rx_table.setColumnCount(5)
            self.rx_table.setHorizontalHeaderLabels(["Time", "ID", "DLC", "Data", "Comment / Message Name"])
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive); self.rx_table.setColumnWidth(0, 100); self.rx_table.setColumnWidth(1, 90); self.rx_table.setColumnWidth(2, 90); self.rx_table.setColumnWidth(3, 380);
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            try: self.rx_table.itemDoubleClicked.disconnect()
            except TypeError: pass
        self.rx_table.setSortingEnabled(True)

    def _create_transmit_panel(self):
        tx_group = QGroupBox("Transmit"); main_layout = QVBoxLayout(tx_group)
        self.tx_table = QTableWidget()
        self.tx_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tx_table.setColumnCount(6); self.tx_table.setHorizontalHeaderLabels(["ID", "DLC", "Data", "Period", "Count", "Comment"])
        header = self.tx_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive) 
        self.tx_table.setColumnWidth(0, 70)   
        self.tx_table.setColumnWidth(1, 65)   
        self.tx_table.setColumnWidth(2, 360)  # Data
        self.tx_table.setColumnWidth(3, 90)   # Period
        self.tx_table.setColumnWidth(4, 90)   # Count
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.tx_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.tx_table)

        panel = QWidget(); panel.setObjectName("TransmitEditPanel")
        grid = QGridLayout(panel); grid.setContentsMargins(10, 8, 10, 8); grid.setSpacing(6)
        
        self.tx_id = SelectAllLineEdit("000"); self.tx_id.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.tx_dlc = SelectAllLineEdit("8"); self.tx_dlc.setValidator(QIntValidator(0, 8))
        self.tx_data_bytes = [SelectAllLineEdit("00") for _ in range(8)]
        for i, b in enumerate(self.tx_data_bytes):
            b.setFixedWidth(30); b.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,2}")))
            b.textChanged.connect(lambda text, index=i: self._on_data_byte_changed(text, index))
        self.tx_comment = QLineEdit(); self.tx_29bit = QCheckBox("29 Bit Id"); self.tx_rtr = QCheckBox("RTR")
        self.tx_period = SelectAllLineEdit("0"); self.tx_period.setValidator(QIntValidator(0, 99999))
        self.tx_mode_combo = QComboBox(); self.tx_mode_combo.addItems(["off", "Periodic", "RTR", "Trigger"])
        self.tx_trigger_id = SelectAllLineEdit(); self.tx_trigger_id.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}")))
        self.tx_trigger_data = SelectAllLineEdit(); self.tx_trigger_data.setEnabled(False)

        grid.addWidget(QLabel("ID"), 0, 0); grid.addWidget(QLabel("DLC"), 0, 1); grid.addWidget(QLabel("Data"), 0, 2)
        grid.addWidget(QLabel("Comment"), 0, 3)
        grid.addWidget(self.tx_id, 1, 0); self.tx_id.setFixedWidth(75)
        grid.addWidget(self.tx_dlc, 1, 1); self.tx_dlc.setFixedWidth(40)
        data_input_layout = QHBoxLayout(); data_input_layout.setSpacing(3)
        for b in self.tx_data_bytes: data_input_layout.addWidget(b)
        grid.addLayout(data_input_layout, 1, 2)
        grid.addWidget(self.tx_comment, 1, 3)
        checkbox_layout = QHBoxLayout(); checkbox_layout.addWidget(self.tx_29bit); checkbox_layout.addWidget(self.tx_rtr); checkbox_layout.addStretch()
        grid.addLayout(checkbox_layout, 2, 0, 1, 2)
        period_layout = QHBoxLayout(); period_layout.addStretch(); period_layout.addWidget(QLabel("Period (ms):")); period_layout.addWidget(self.tx_period)
        grid.addLayout(period_layout, 2, 2)
        trigger_layout = QHBoxLayout(); trigger_layout.addWidget(QLabel("TX Mode:")); trigger_layout.addWidget(self.tx_mode_combo)
        trigger_layout.addSpacing(15); trigger_layout.addWidget(QLabel("Trigger ID:")); trigger_layout.addWidget(self.tx_trigger_id)
        trigger_layout.addSpacing(15); trigger_layout.addWidget(QLabel("Trigger Data:")); trigger_layout.addWidget(self.tx_trigger_data)
        trigger_layout.addStretch(); grid.addLayout(trigger_layout, 3, 0, 1, 4)
        
        button_grid = QGridLayout(); button_grid.setSpacing(5)
        btn_single_shot = QPushButton("Single Shot", clicked=self.send_single_shot)
        btn_add = QPushButton("Add", clicked=self.add_tx_message)
        btn_send_all = QPushButton("Send All", clicked=self.send_all_tx_messages)
        btn_delete = QPushButton("Delete", clicked=self.delete_tx_message)
        btn_delete_all = QPushButton("Delete All", clicked=self.delete_all_tx_messages)
        btn_clear = QPushButton("Clear", clicked=self.clear_transmit_panel)
        btn_clear.setToolTip("Arrête toutes les transmissions et réinitialise la liste d'envoi.")

        button_grid.addWidget(btn_single_shot, 0, 0); button_grid.addWidget(btn_add, 0, 1)
        button_grid.addWidget(btn_send_all, 1, 0); button_grid.addWidget(btn_clear, 1, 1)
        button_grid.addWidget(btn_delete, 2, 0); button_grid.addWidget(btn_delete_all, 2, 1)
        grid.addLayout(button_grid, 0, 4, 4, 1); grid.setColumnStretch(3, 1)
        
        main_layout.addWidget(panel)
        
        scenario_group = QGroupBox("Sequence/Scenario Control")
        scenario_layout = QHBoxLayout(scenario_group)
        
        scenario_layout.addWidget(QLabel("Scenario :"))
        self.scenario_combo = QComboBox()
        self.scenario_combo.setToolTip("Select a scenario (grouped by 'Comment') to execute.")
        scenario_layout.addWidget(self.scenario_combo, 1)

        scenario_layout.addSpacing(15)
        
        scenario_layout.addWidget(QLabel("Delay (ms) :"))
        self.sequence_delay_edit = QLineEdit("200")
        self.sequence_delay_edit.setValidator(QIntValidator(0, 5000))
        self.sequence_delay_edit.setFixedWidth(50)
        self.sequence_delay_edit.setToolTip("Delay between the first frame (impulse) and the rest of the scenario.")
        scenario_layout.addWidget(self.sequence_delay_edit)
        
        btn_activate_scenario = QPushButton("Activate Scenario")
        btn_activate_scenario.setToolTip("Exécute le scénario sélectionné :\n1. Envoie la 1ère trame du groupe en Single Shot.\n2. Attend le délai spécifié.\n3. Lance les autres trames du groupe en mode périodique.")
        btn_activate_scenario.clicked.connect(self.activate_scenario)
        scenario_layout.addWidget(btn_activate_scenario)

        main_layout.addWidget(scenario_group)
        
        self.tx_id.returnPressed.connect(self._focus_on_dlc)
        self.tx_dlc.returnPressed.connect(self._focus_on_data)

        for widget in [self.tx_id, self.tx_period, self.tx_comment, self.tx_trigger_id] + self.tx_data_bytes:
            widget.editingFinished.connect(self._update_tx_table_from_form)
        self.tx_dlc.textChanged.connect(self._update_tx_table_from_form)
        for checkbox in [self.tx_29bit, self.tx_rtr]: checkbox.stateChanged.connect(self._update_tx_table_from_form)
        self.tx_mode_combo.currentIndexChanged.connect(self._update_tx_table_from_form)
        self.tx_29bit.stateChanged.connect(self._update_id_validator); self.tx_dlc.textChanged.connect(self._update_data_fields_state)
        self.tx_rtr.stateChanged.connect(self._update_data_fields_state); self.tx_mode_combo.currentIndexChanged.connect(self._update_tx_mode_ui)
        
        self._update_id_validator(); self._update_data_fields_state(); self._update_tx_mode_ui()
        self._create_default_tx_row()
        
        self.tx_table.itemSelectionChanged.connect(self.copy_tx_table_to_form)
        
        return tx_group

    def _focus_on_dlc(self):
        self.tx_dlc.setFocus()

    def _focus_on_data(self):
        if self.tx_data_bytes[0].isEnabled():
            self.tx_data_bytes[0].setFocus()

    def _update_id_validator(self):
        is_29bit = self.tx_29bit.isChecked()
        self.tx_id.setMaxLength(8 if is_29bit else 3)
        self.tx_id.setPlaceholderText("")
        current_text = self.tx_id.text()
        if not current_text or current_text == "000" or current_text == "00000000":
            self.tx_id.setText("00000000" if is_29bit else "000")
        elif not is_29bit and len(current_text) > 3:
            self.tx_id.setText(current_text[:3])
    
    def _update_data_fields_state(self):
        dlc_val = 8; is_rtr = self.tx_rtr.isChecked()
        if self.tx_dlc.text().isdigit(): dlc_val = int(self.tx_dlc.text())
        for i, data_byte_edit in enumerate(self.tx_data_bytes):
            is_enabled = i < dlc_val and not is_rtr
            data_byte_edit.setEnabled(is_enabled)
            if not is_enabled: data_byte_edit.clear()
            elif is_enabled and not data_byte_edit.text(): data_byte_edit.setText("00")

    def _update_tx_mode_ui(self):
        mode = self.tx_mode_combo.currentText()
        self.tx_period.setEnabled(mode == "Periodic"); self.tx_trigger_id.setEnabled(mode == "Trigger")

    def _on_data_byte_changed(self, text, index):
        if len(text) == 2 and index < 7:
            next_field = self.tx_data_bytes[index + 1]
            if next_field.isEnabled(): next_field.setFocus()
    
    def _update_tx_table_from_form(self):
        selected_rows = self.tx_table.selectionModel().selectedRows()
        row = selected_rows[0].row() if selected_rows else 0
        if self.tx_table.rowCount() == 0: return
        
        sender = self.sender()
        if isinstance(sender, QCheckBox) or isinstance(sender, QLineEdit):
            if sender == self.tx_29bit: self._update_id_validator()
            if sender == self.tx_dlc or sender == self.tx_rtr: self._update_data_fields_state()
        if isinstance(sender, QComboBox):
            if sender == self.tx_mode_combo: self._update_tx_mode_ui()

        self.tx_table.blockSignals(True)
        self.tx_table.item(row, 0).setText(self.tx_id.text().upper())
        self.tx_table.item(row, 1).setText(self.tx_dlc.text())
        self.tx_table.item(row, 2).setText(" ".join([f.text().upper().zfill(2) for f in self.tx_data_bytes if f.isEnabled() and f.text().strip()]))
        period_item = self.tx_table.item(row, 3)
        mode = self.tx_mode_combo.currentText()
        if mode == "Periodic": period_item.setText(self.tx_period.text())
        else: period_item.setText(mode)
        period_item.setData(self.TX_MODE_ROLE, mode); period_item.setData(self.TRIGGER_ID_ROLE, self.tx_trigger_id.text().upper())
        self.tx_table.item(row, 5).setText(self.tx_comment.text())
        self.tx_table.blockSignals(False)
        
    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.connection_status_label = QLabel("Not Connected")
        self.filter_status_label = QLabel("Filter: Off")
        self.connection_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.filter_status_label.setStyleSheet("color: red; font-weight: bold;")
        separator = QLabel("    |   ")
        separator.setStyleSheet("color: red; font-weight: bold;")

        self.status_bar.addPermanentWidget(self.connection_status_label)
        self.status_bar.addPermanentWidget(separator)
        self.status_bar.addPermanentWidget(self.filter_status_label)
      
    def toggle_receive_mode(self, checked):
        self.is_monitoring = checked
        
        if self.is_monitoring:
            self.actions["trace_monitor"].setText("Monitor")
        else:
            self.actions["trace_monitor"].setText("Tracer")
            
        self._setup_receive_table(); self.monitor_id_to_row.clear() 
        if self.is_monitoring: self._repopulate_monitor_from_cache()
        else: self._repopulate_tracer_from_cache()

    def _repopulate_monitor_from_cache(self):
        self.rx_table.setSortingEnabled(False)
        for msg_id in sorted(self.monitor_data_cache.keys()):
            cache_entry = self.monitor_data_cache[msg_id]
            row = self.rx_table.rowCount(); self.rx_table.insertRow(row); self.monitor_id_to_row[msg_id] = row 
            self.rx_table.setItem(row, 0, QTableWidgetItem(f"{msg_id:X}")); self.rx_table.setItem(row, 1, NumericTableWidgetItem(str(cache_entry['dlc'])))
            self.rx_table.setItem(row, 2, QTableWidgetItem(cache_entry['data'])); self.rx_table.setItem(row, 3, NumericTableWidgetItem(f"{cache_entry.get('period', 0.0):.2f}"))
            self.rx_table.setItem(row, 4, NumericTableWidgetItem(str(cache_entry['count']))); self.rx_table.setItem(row, 5, QTableWidgetItem(cache_entry.get('comment', '')))
        self.rx_table.setSortingEnabled(True)

    def _repopulate_tracer_from_cache(self):
        self.rx_table.setSortingEnabled(False)
        for msg, name in self.tracer_data_cache:
            self._add_tracer_row(msg, name, scroll=False)
        self.rx_table.scrollToBottom()
        self.rx_table.setSortingEnabled(True)

    def _update_monitor_cache(self, msg: can.Message, message_name=""):
        msg_id = msg.arbitration_id
        new_data_str = msg.data.hex(' ').upper()
        
        if msg_id in self.monitor_data_cache:
            cache_entry = self.monitor_data_cache[msg_id]
            
            # --- HIGHLIGHT : Détecter le changement ---
            if new_data_str != cache_entry.get('data', ''):
                cache_entry['changed'] = True
            else:
                cache_entry['changed'] = False

            cache_entry['period'] = (msg.timestamp - cache_entry['last_ts']) * 1000
            cache_entry['last_ts'] = msg.timestamp
            cache_entry['data'] = new_data_str
            cache_entry['count'] += 1
            cache_entry['dlc'] = msg.dlc
            if self.dbc_manager.is_loaded():
                cache_entry['comment'] = message_name
        else:
            self.monitor_data_cache[msg_id] = { 
                'dlc': msg.dlc, 
                'data': new_data_str, 
                'count': 1, 
                'last_ts': msg.timestamp, 
                'period': 0.0, 
                'comment': message_name,
                # --- HIGHLIGHT : Marquer comme changé à la création ---
                'changed': True 
            }

    def _update_monitor_view(self, msg: can.Message):
        msg_id = msg.arbitration_id
        if msg_id not in self.monitor_data_cache: return
        cache_entry = self.monitor_data_cache[msg_id]
        
        if msg_id in self.monitor_id_to_row:
            row = self.monitor_id_to_row[msg_id]
            self.rx_table.item(row, 1).setText(str(cache_entry['dlc']))
            self.rx_table.item(row, 2).setText(cache_entry['data'])
            self.rx_table.item(row, 3).setText(f"{cache_entry['period']:.2f}")
            self.rx_table.item(row, 4).setText(str(cache_entry['count']))
            self.rx_table.item(row, 5).setText(cache_entry.get('comment', ''))

            # --- HIGHLIGHT : Appeler la surbrillance si changé ---
            if cache_entry.get('changed', False):
                self.highlight_row(row, 150)

        else:
            sorting_enabled = self.rx_table.isSortingEnabled()
            self.rx_table.setSortingEnabled(False)
            row = self.rx_table.rowCount()
            self.rx_table.insertRow(row)
            self.monitor_id_to_row[msg_id] = row
            
            self.rx_table.setItem(row, 0, QTableWidgetItem(f"{msg_id:X}"))
            self.rx_table.setItem(row, 1, NumericTableWidgetItem(str(cache_entry['dlc'])))
            self.rx_table.setItem(row, 2, QTableWidgetItem(cache_entry['data']))
            self.rx_table.setItem(row, 3, NumericTableWidgetItem(f"{cache_entry['period']:.2f}"))
            self.rx_table.setItem(row, 4, NumericTableWidgetItem(str(cache_entry['count'])))
            self.rx_table.setItem(row, 5, QTableWidgetItem(cache_entry.get('comment', '')))
            
            self.rx_table.setSortingEnabled(sorting_enabled)
            # --- HIGHLIGHT : Appeler la surbrillance pour les nouvelles lignes ---
            self.highlight_row(row, 150)

    def _add_tracer_row(self, msg: can.Message, message_name="", scroll=True):
        relative_time = msg.timestamp - self.start_time; row = self.rx_table.rowCount(); self.rx_table.insertRow(row)
        self.rx_table.setItem(row, 0, NumericTableWidgetItem(f"{relative_time:.3f}")); self.rx_table.setItem(row, 1, QTableWidgetItem(f"{msg.arbitration_id:X}"))
        self.rx_table.setItem(row, 2, NumericTableWidgetItem(str(msg.dlc))); self.rx_table.setItem(row, 3, QTableWidgetItem(msg.data.hex(' ').upper())); 
        self.rx_table.setItem(row, 4, QTableWidgetItem(message_name))
        if scroll: self.rx_table.scrollToBottom()
        if self.trace_save_file:
            self.trace_save_buffer.append([f"{relative_time:.3f}", f"{msg.arbitration_id:X}", f"{msg.dlc}", msg.data.hex(' ').upper(), message_name])

    def handle_can_message(self, msg: can.Message):
        if not self.start_time: self.start_time = msg.timestamp
        
        for row in range(self.tx_table.rowCount()):
            period_item = self.tx_table.item(row, 3)
            if not period_item: continue
            tx_mode = period_item.data(self.TX_MODE_ROLE)
            try:
                tx_id = int(self.tx_table.item(row, 0).text(), 16)
                if tx_mode == "RTR" and msg.is_remote_frame and msg.arbitration_id == tx_id:
                    response_msg = self._get_message_from_table_row(row, force_not_rtr=True)
                    if response_msg and self.can_worker.send_message(response_msg): self._increment_tx_count(row)
                elif tx_mode == "Trigger":
                    trigger_id_text = period_item.data(self.TRIGGER_ID_ROLE)
                    if trigger_id_text and msg.arbitration_id == int(trigger_id_text, 16):
                        triggered_msg = self._get_message_from_table_row(row)
                        if triggered_msg and self.can_worker.send_message(triggered_msg): self._increment_tx_count(row)
            except (ValueError, AttributeError): continue
            
        # --- DBC ---
        message_name = self.dbc_manager.get_message_name(msg.arbitration_id)
            
        self._update_monitor_cache(msg, message_name)
        self.tracer_data_cache.append((msg, message_name))
        
        try:
            if self.is_monitoring:
                self._update_monitor_view(msg)
            else:
                self._add_tracer_row(msg, message_name)
        except Exception as e: print(f"Display Error: {e}")

    def copy_rx_to_tx_form(self, index):
        if not index or not index.isValid(): return
        row = index.row()
        if self.is_monitoring: id_text, dlc_text, data_text = (self.rx_table.item(row, i).text() if self.rx_table.item(row, i) else "" for i in [0,1,2])
        else: id_text, dlc_text, data_text = (self.rx_table.item(row, i).text() if self.rx_table.item(row, i) else "" for i in [1,2,3])
        
        self.tx_29bit.setChecked(len(id_text) > 3)
        self.tx_id.setText(id_text); self.tx_dlc.setText(dlc_text)
        data_bytes = data_text.split()
        for i in range(8): self.tx_data_bytes[i].setText(data_bytes[i] if i < len(data_bytes) else "00")
        self._update_data_fields_state()
                
    def copy_tx_table_to_form(self):
        selected_rows = self.tx_table.selectionModel().selectedRows()
        if not selected_rows: return
        row = selected_rows[0].row()

        for widget in [self.tx_id, self.tx_dlc, self.tx_period, self.tx_comment, self.tx_trigger_id] + self.tx_data_bytes + [self.tx_mode_combo, self.tx_29bit, self.tx_rtr]:
            widget.blockSignals(True)

        id_text = self.tx_table.item(row, 0).text(); self.tx_29bit.setChecked(len(id_text) > 3); self.tx_id.setText(id_text); self.tx_dlc.setText(self.tx_table.item(row, 1).text())
        period_item = self.tx_table.item(row, 3)
        mode = period_item.data(self.TX_MODE_ROLE) if period_item else "off"; trigger_id = period_item.data(self.TRIGGER_ID_ROLE) if period_item else ""
        self.tx_mode_combo.setCurrentText(mode); self.tx_trigger_id.setText(trigger_id)
        if mode == "Periodic": self.tx_period.setText(period_item.text())
        else: self.tx_period.setText("0")
        self.tx_comment.setText(self.tx_table.item(row, 5).text()); data_bytes = self.tx_table.item(row, 2).text().split()
        for i in range(8): self.tx_data_bytes[i].setText(data_bytes[i] if i < len(data_bytes) else "00")
        
        for widget in [self.tx_id, self.tx_dlc, self.tx_period, self.tx_comment, self.tx_trigger_id] + self.tx_data_bytes + [self.tx_mode_combo, self.tx_29bit, self.tx_rtr]:
            widget.blockSignals(False)

        self._update_id_validator(); self._update_data_fields_state(); self._update_tx_mode_ui()

    def show_connect_dialog(self):
        if self.can_worker and self.can_worker.isRunning(): self.disconnect_can(); return
        dialog = ConnectDialog(self)
        if dialog.exec():
            port = dialog.get_selected_port()
            if "No COM" in port: QMessageBox.warning(self, "Connection Error", "No COM port selected."); return
            
            self.reset_all(); self.start_time = 0 
            
            self.can_worker = CanWorker(
                interface=self.settings.get("can_device"), 
                channel=port, 
                baudrate=self.settings.get("can_baudrate"), 
                com_baudrate=self.settings.get("com_baudrate"), 
                listen_only=self.settings.get("listen_only"), 
                can_filters=self.mask_filters,
                range_filter={'enabled': self.range_filter_enabled, **self.range_filter},
                discrete_filter={'enabled': self.discrete_filter_enabled, 'ids': self.discrete_filters}
            )
            
            self.can_worker.message_received.connect(self.handle_can_message); self.can_worker.error_occurred.connect(self.handle_can_error)
            self.can_worker.connection_status.connect(self.update_connection_status); self.can_worker.start(); self.status_bar.showMessage(f"Connecting to {port}...", 5000)
                
    def disconnect_can(self):
        self._flush_save_buffers(); self.save_timer.stop(); self.trace_save_file = None; self.tx_save_file = None
        if self.can_worker: self.can_worker.stop(); self.can_worker = None
        self.update_connection_status(False)

    def update_connection_status(self, is_connected):
        self.actions["connect"].setText("Disconnect" if is_connected else "Connect")
        self.connection_status_label.setText("Connected" if is_connected else "Not Connected")
        if not is_connected:
            self._stop_all_timers()

    def check_connection_status(self):
        if self.can_worker and not self.can_worker.isRunning(): self.disconnect_can()
        
    def handle_can_error(self, error): 
        QMessageBox.critical(self, "CAN Error", error); self.disconnect_can()
        
    def reset_all(self):
        self._stop_all_timers()
        self.rx_table.setRowCount(0); self.monitor_id_to_row.clear(); self.monitor_data_cache.clear(); self.tracer_data_cache.clear()
        self.start_time = 0
        self.clear_transmit_panel(confirm=False)
        self.status_bar.showMessage("Application reset.", 2000)

    def _reset_transmit_form(self):
        widgets_to_block = [self.tx_id, self.tx_dlc, self.tx_period, self.tx_comment, self.tx_trigger_id] + \
                           self.tx_data_bytes + [self.tx_mode_combo, self.tx_29bit, self.tx_rtr]
        for widget in widgets_to_block: widget.blockSignals(True)
        self.tx_id.setText("000"); self.tx_dlc.setText("8")
        for byte_edit in self.tx_data_bytes: byte_edit.setText("00")
        self.tx_comment.clear(); self.tx_period.setText("0"); self.tx_trigger_id.clear()
        self.tx_29bit.setChecked(False); self.tx_rtr.setChecked(False); self.tx_mode_combo.setCurrentIndex(0)
        for widget in widgets_to_block: widget.blockSignals(False)
        self._update_data_fields_state(); self._update_tx_mode_ui()

    def save_rx_tracer_data(self):
        if not self.tracer_data_cache: QMessageBox.information(self, "Save Rx Tracer", "No trace data to save."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save Rx Tracer", "rx_tracer", "Text Files (*.txt);;CSV Files (*.csv)")
        if not path: return
        self._save_tracer_to_file(path); self.trace_save_file = path; self.trace_save_buffer.clear(); self.save_timer.start(2000)
        self.status_bar.showMessage(f"Rx Tracer saved to {path}. Real-time recording enabled.", 5000)

    def save_rx_monitor_data(self):
        if not self.monitor_data_cache: QMessageBox.information(self, "Save Rx Monitor", "No monitor data to save."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save Rx Monitor", "rx_monitor", "Text Files (*.txt);;CSV Files (*.csv)")
        if not path: return
        self._save_monitor_to_file(path); self.status_bar.showMessage(f"Rx Monitor saved to {path}", 3000)

    def _save_tracer_to_file(self, path):
        headers = ["Time", "ID", "DLC", "Data", "Message Name"]
        data_to_save = []
        for msg, name in self.tracer_data_cache:
            data_to_save.append([f"{(msg.timestamp - self.start_time):.3f}", f"{msg.arbitration_id:X}", str(msg.dlc), msg.data.hex(' ').upper(), name])
        self._save_data_to_file_generic(path, headers, data_to_save)

    def _save_monitor_to_file(self, path):
        headers = ["ID", "DLC", "Data", "Period", "Count", "Message Name"]
        data_to_save = []
        for msg_id in sorted(self.monitor_data_cache.keys()):
            cache_entry = self.monitor_data_cache[msg_id]
            data_to_save.append([f"{msg_id:X}", str(cache_entry['dlc']), cache_entry['data'], f"{cache_entry.get('period', 0.0):.2f}", str(cache_entry['count']), cache_entry.get('comment', '')])
        self._save_data_to_file_generic(path, headers, data_to_save)

    def _save_data_to_file_generic(self, path, headers, data_rows):
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                if path.endswith('.txt'):
                    col_widths = [len(h) for h in headers]
                    for row in data_rows:
                        for i, cell in enumerate(row):
                            if len(str(cell)) > col_widths[i]: col_widths[i] = len(str(cell))
                    f.write("  ".join([h.ljust(w) for h, w in zip(headers, col_widths)]) + "\n")
                    for row in data_rows: f.write("  ".join([str(d).ljust(w) for d, w in zip(row, col_widths)]) + "\n")
                else: writer = csv.writer(f, delimiter=';'); writer.writerow(headers); writer.writerows(data_rows)
        except Exception as e: QMessageBox.critical(self, "Save Error", f"Failed to save file:\n{e}")

    def load_tx_list(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Tx List", "", "CSV Files (*.csv)")
        if path: self._load_from_file(path)

    def save_tx_list(self):
        if self.tx_table.rowCount() <= 1: 
            QMessageBox.information(self, "Save Tx List", "The transmit list is empty."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save Tx List", "tx_list", "Text Files (*.txt);;CSV Files (*.csv)")
        if path: self._save_table_to_file(path); self.status_bar.showMessage(f"TX list saved to {path}.", 3000)

    def _save_table_to_file(self, path):
        headers = ["ID", "DLC", "Data", "Period", "Count", "Comment", "Trigger ID"]
        data_rows = []
        for row in range(1, self.tx_table.rowCount()):
            period_item = self.tx_table.item(row, 3)
            trigger_id = period_item.data(self.TRIGGER_ID_ROLE) if period_item else ""
            period_val_or_mode = period_item.text()
            row_data = [self.tx_table.item(row, c).text() if self.tx_table.item(row, c) else "" for c in [0, 1, 2]]
            row_data.extend([
                period_val_or_mode, 
                self.tx_table.item(row, 4).text(), 
                self.tx_table.item(row, 5).text(), 
                trigger_id                        
            ])
            data_rows.append(row_data)
        self._save_data_to_file_generic(path, headers, data_rows)
    
    def _load_from_file(self, path):
        try:
            self.clear_transmit_panel(confirm=False)
            
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=';')
                headers = next(reader, None)

                is_first_row = True
                for row_data in reader:
                    if len(row_data) < 7: continue

                    if is_first_row:
                        row_to_populate = 0
                        is_first_row = False
                    else:
                        row_to_populate = self.tx_table.rowCount()
                        self._create_or_get_row(row_to_populate)
                    
                    can_id, dlc, data, period_val_or_mode, count, comment, trigger_id = row_data[:7]

                    self.tx_table.item(row_to_populate, 0).setText(can_id)
                    self.tx_table.item(row_to_populate, 1).setText(dlc)
                    self.tx_table.item(row_to_populate, 2).setText(data)
                    self.tx_table.item(row_to_populate, 4).setText(count)
                    self.tx_table.item(row_to_populate, 5).setText(comment)
                    
                    period_item = self.tx_table.item(row_to_populate, 3)
                    tx_mode = "off"
                    if period_val_or_mode.isdigit() and int(period_val_or_mode) > 0:
                        tx_mode = "Periodic"
                    elif period_val_or_mode in ["off", "RTR", "Trigger"]:
                        tx_mode = period_val_or_mode
                    
                    period_item.setText(period_val_or_mode)
                    period_item.setData(self.TX_MODE_ROLE, tx_mode)
                    period_item.setData(self.TRIGGER_ID_ROLE, trigger_id)

            self.tx_table.selectRow(0)
            self.copy_tx_table_to_form()
            self.status_bar.showMessage(f"File loaded: {path}", 3000)
            self._update_scenario_list()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load or parse file:\n{e}")
            
    def _edit_rx_comment(self, item):
        if self.is_monitoring and item.column() == 5:
            if not self.dbc_manager.is_loaded():
                self.rx_table.editItem(item)

    def _on_rx_comment_changed(self, item):
        if not self.is_monitoring or item.column() != 5: return
        if self.dbc_manager.is_loaded(): return
        
        row = item.row(); id_item = self.rx_table.item(row, 0)
        if not id_item: return
        try: msg_id = int(id_item.text(), 16)
        except (ValueError, KeyError): return
        if msg_id in self.monitor_data_cache: self.monitor_data_cache[msg_id]['comment'] = item.text()

    def show_settings_dialog(self):
        dialog = SettingsDialog(self);
        if dialog.exec(): self.settings = dialog.get_settings(); self.status_bar.showMessage("Settings updated. Reconnect to apply.", 3000)
    
    def show_filter_dialog(self):
        dialog = FilterDialog(self)
        if dialog.exec():
            filters = dialog.get_filters()
            self.mask_filters = filters.get('mask', [])
            self.range_filter = filters.get('range', {})
            self.discrete_filters = filters.get('discrete_ids', [])
            
            self.range_filter_enabled = filters.get('range_enabled', False) and bool(self.range_filter)
            self.discrete_filter_enabled = filters.get('discrete_enabled', False) and bool(self.discrete_filters)

            mask_filter_on = filters.get('mask_enabled', False)
            filter_on = mask_filter_on or self.range_filter_enabled or self.discrete_filter_enabled
            
            self.filter_status_label.setText("Filter: On" if filter_on else "Filter: Off")
            self.status_bar.showMessage("Filters updated. Reconnect to apply mask filters.", 3000)

    def _get_message_from_form(self):
        try:
            if not self.tx_id.text() or not self.tx_dlc.text(): raise ValueError("ID and DLC are required")
            msg_id = int(self.tx_id.text(), 16); dlc = int(self.tx_dlc.text())
            data = bytes.fromhex("".join([f.text() for f in self.tx_data_bytes if f.isEnabled() and f.text().strip()]))
            if len(data) != dlc and not self.tx_rtr.isChecked(): raise ValueError(f"DLC mismatch ({dlc}) and data length ({len(data)} bytes)")
            return can.Message(arbitration_id=msg_id, is_extended_id=self.tx_29bit.isChecked(), is_remote_frame=self.tx_rtr.isChecked(), dlc=dlc, data=data)
        except Exception as e: QMessageBox.warning(self, "Invalid Message", f"Cannot create message: {e}"); return None
        
    def _get_message_from_table_row(self, row, force_not_rtr=False):
        try:
            is_rtr_flag = False
            selected_rows = self.tx_table.selectionModel().selectedRows()
            if selected_rows and selected_rows[0].row() == row:
                is_rtr_flag = self.tx_rtr.isChecked()
            if force_not_rtr: is_rtr_flag = False
            id_text = self.tx_table.item(row, 0).text()
            msg_id = int(id_text, 16)
            dlc = int(self.tx_table.item(row, 1).text())
            data_text = self.tx_table.item(row, 2).text().replace(" ", "")
            data = bytes.fromhex(data_text) if data_text else b''
            is_extended = len(id_text) > 3
            return can.Message(arbitration_id=msg_id, is_extended_id=is_extended, is_remote_frame=is_rtr_flag, dlc=dlc, data=data)
        except Exception as e: print(f"Error parsing row {row}: {e}"); return None
        
    def send_single_shot(self):
        if not (self.can_worker and self.can_worker.isRunning()): self.handle_can_error("Not connected."); return
        msg = self._get_message_from_form()
        if msg and self.can_worker.send_message(msg): self.status_bar.showMessage(f"Test message ID {msg.arbitration_id:X} sent.", 2000)
        
    def _create_default_tx_row(self):
        self._create_or_get_row(0)
        self.tx_table.selectRow(0)
        self._update_tx_table_from_form()

    def add_tx_message(self):
        if not self.tx_id.text() or not self.tx_dlc.text():
            QMessageBox.warning(self, "Required Fields", "Please enter at least an ID and a DLC."); return
        
        row_position = self.tx_table.rowCount()
        self._create_or_get_row(row_position)

        id_text = self.tx_id.text().upper(); dlc_text = self.tx_dlc.text()
        data_text = " ".join([f.text().upper().zfill(2) for f in self.tx_data_bytes if f.isEnabled() and f.text().strip()])
        mode = self.tx_mode_combo.currentText()
        period_text = self.tx_period.text() if mode == "Periodic" else mode
        comment_text = self.tx_comment.text(); trigger_id = self.tx_trigger_id.text().upper()

        self.tx_table.setItem(row_position, 0, QTableWidgetItem(id_text))
        self.tx_table.setItem(row_position, 1, QTableWidgetItem(dlc_text))
        self.tx_table.setItem(row_position, 2, QTableWidgetItem(data_text))
        period_item = self.tx_table.item(row_position, 3); period_item.setText(period_text)
        period_item.setData(self.TX_MODE_ROLE, mode); period_item.setData(self.TRIGGER_ID_ROLE, trigger_id)
        self.tx_table.setItem(row_position, 4, QTableWidgetItem("0"))
        self.tx_table.setItem(row_position, 5, QTableWidgetItem(comment_text))
        self.tx_table.selectRow(row_position)
        self._update_scenario_list()
    
    def _create_or_get_row(self, row):
        if row >= self.tx_table.rowCount(): self.tx_table.insertRow(row)
        for i in range(self.tx_table.columnCount()):
            if not self.tx_table.item(row, i): self.tx_table.setItem(row, i, QTableWidgetItem())
        if not self.tx_table.item(row, 4) or not self.tx_table.item(row, 4).text():
            self.tx_table.setItem(row, 4, QTableWidgetItem("0"))
        return row

    def delete_tx_message(self):
        selected_rows = self.tx_table.selectionModel().selectedRows()
        if not selected_rows: QMessageBox.information(self, "Information", "Please select one or more rows to delete."); return
        
        if selected_rows[0].row() == 0:
            QMessageBox.warning(self, "Action Forbidden", "The first working row cannot be deleted."); return
        
        for index in sorted(selected_rows, key=lambda i: i.row(), reverse=True):
            if index.row() == 0: continue
            if index.row() in self.tx_periodic_timers: self.tx_periodic_timers.pop(index.row()).stop()
            self.tx_table.removeRow(index.row())
        self._update_scenario_list()
    
    def delete_all_tx_messages(self):
        if self.tx_table.rowCount() <= 1: return
        self._stop_all_timers()
        while self.tx_table.rowCount() > 1: self.tx_table.removeRow(1)
        self.tx_table.selectRow(0); self.copy_tx_table_to_form()
        self.status_bar.showMessage("Transmit list cleared.", 2000)
        self._update_scenario_list()

    def send_all_tx_messages(self):
        if not (self.can_worker and self.can_worker.isRunning()): self.handle_can_error("Not connected."); return
        self._stop_all_timers()
        periodic_count = 0
        for row in range(self.tx_table.rowCount()):
            period_item = self.tx_table.item(row, 3);
            if not period_item: continue
            
            tx_mode = period_item.data(self.TX_MODE_ROLE)
            if tx_mode != "Periodic": continue
            
            period_ms = 0
            if period_item.text().isdigit(): period_ms = int(period_item.text())
            
            msg = self._get_message_from_table_row(row)
            if not msg: continue
            if period_ms > 0: 
                timer = QTimer(self); timer.timeout.connect(lambda r=row: self.send_periodic_message(r))
                timer.start(period_ms); self.tx_periodic_timers[row] = timer; periodic_count += 1
        
        if periodic_count > 0:
            self.status_bar.showMessage(f"{periodic_count} envoi(s) périodique(s) démarré(s).", 4000)

    def _stop_all_timers(self):
        if not self.tx_periodic_timers:
            return
        for timer in self.tx_periodic_timers.values():
            timer.stop()
        self.tx_periodic_timers.clear()

    def clear_transmit_panel(self, confirm=True):
        if confirm:
            reply = QMessageBox.question(self, "Confirmer la Réinitialisation",
                                         "Voulez-vous vraiment arrêter toutes les transmissions et vider la liste d'envoi ?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self._stop_all_timers()
        
        while self.tx_table.rowCount() > 1:
            self.tx_table.removeRow(1)

        self._reset_transmit_form()
        self._update_tx_table_from_form()
        self.tx_table.selectRow(0)
        self._update_scenario_list()

        if confirm:
            self.status_bar.showMessage("Panneau de transmission réinitialisé.", 3000)

    def send_periodic_message(self, row):
        msg = self._get_message_from_table_row(row)
        if msg and self.can_worker and self.can_worker.isRunning() and self.can_worker.send_message(msg): self._increment_tx_count(row)

    def _increment_tx_count(self, row):
        if (count_item := self.tx_table.item(row, 4)):
            current_count = int(count_item.text()) if count_item.text().isdigit() else 0
            count_item.setText(str(current_count + 1))
            
    def _flush_save_buffers(self):
        if self.trace_save_file and self.trace_save_buffer:
            try:
                with open(self.trace_save_file, 'a', newline='', encoding='utf-8') as f:
                    if self.trace_save_file.endswith('.csv'):
                        writer = csv.writer(f, delimiter=';')
                        writer.writerows(self.trace_save_buffer)
                    else:
                        for buffer_line in self.trace_save_buffer:
                            f.write("  ".join(buffer_line) + "\n")
                self.trace_save_buffer.clear()
            except Exception as e: print(f"Error flushing trace buffer: {e}")
            
    def _update_scenario_list(self):
        self.scenario_combo.blockSignals(True)
        current_selection = self.scenario_combo.currentText()
        self.scenario_combo.clear()
        
        scenarios = set()
        for row in range(self.tx_table.rowCount()):
            if (comment_item := self.tx_table.item(row, 5)) and comment_item.text():
                scenarios.add(comment_item.text().strip())

        if scenarios:
            sorted_scenarios = sorted(list(scenarios))
            self.scenario_combo.addItems(sorted_scenarios)
            if current_selection in sorted_scenarios:
                self.scenario_combo.setCurrentText(current_selection)
                
        self.scenario_combo.blockSignals(False)

    def activate_scenario(self):
        if not (self.can_worker and self.can_worker.isRunning()):
            self.handle_can_error("Not connected.")
            return

        scenario_name = self.scenario_combo.currentText()
        if not scenario_name:
            QMessageBox.warning(self, "Erreur de Scénario", "Aucun scénario sélectionné.")
            return
            
        try:
            delay_ms = int(self.sequence_delay_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Erreur de Scénario", "Le délai doit être un nombre valide.")
            return

        self._stop_all_timers()

        scenario_rows = []
        for row in range(self.tx_table.rowCount()):
            if (item := self.tx_table.item(row, 5)) and item.text().strip() == scenario_name:
                scenario_rows.append(row)

        if not scenario_rows:
            QMessageBox.information(self, "Info", f"Aucune ligne trouvée pour le scénario '{scenario_name}'.")
            return

        first_row = scenario_rows.pop(0)
        msg_init = self._get_message_from_table_row(first_row)
        if msg_init and self.can_worker.send_message(msg_init):
            self._increment_tx_count(first_row)
            self.status_bar.showMessage(f"Scénario '{scenario_name}' [1/2]: Impulsion envoyée. Démarrage de l'environnement dans {delay_ms} ms.", 5000)

            QTimer.singleShot(delay_ms, lambda: self._activate_scenario_periodic_part(scenario_name, scenario_rows))
        else:
            QMessageBox.warning(self, "Erreur de Scénario", f"Impossible d'envoyer la trame d'initialisation pour le scénario '{scenario_name}'.")

    def _activate_scenario_periodic_part(self, scenario_name, periodic_rows):
        periodic_count = 0
        for row in periodic_rows:
            try:
                if (mode_item := self.tx_table.item(row, 3)) and mode_item.data(self.TX_MODE_ROLE) == "Periodic":
                    period_ms = int(mode_item.text())
                    if period_ms > 0:
                        msg = self._get_message_from_table_row(row)
                        if not msg: continue
                        
                        timer = QTimer(self)
                        timer.timeout.connect(lambda r=row: self.send_periodic_message(r))
                        timer.start(period_ms)
                        self.tx_periodic_timers[row] = timer
                        periodic_count += 1
            except (ValueError, AttributeError, IndexError):
                continue

        self.status_bar.showMessage(f"Scénario '{scenario_name}' [2/2]: Environnement activé ({periodic_count} trames).", 5000)
            
    # --- MODIFIÉ ---
    # Renommage de _handle_load_dbc en _handle_load_dbc_file
    def _handle_load_dbc_file(self):
        """Gère le clic sur l'action "Load File...", appelle le manager et met à jour l'UI."""
        file_name = self.dbc_manager.load_file(self)
        if file_name:
            self.setWindowTitle(f"CANLab - [{file_name}]")
            self.reset_all_views()
        elif not self.dbc_manager.is_loaded():
            self.setWindowTitle("CANLab")
            
    def _handle_load_dbc_folder(self):
        """Gère le clic sur l'action "Load DBC FoldeR", appelle le manager et met à jour l'UI."""
        folder_name = self.dbc_manager.load_folder(self)
        if folder_name:
            self.setWindowTitle(f"CANLab - [DBC: {folder_name}]")
            self.reset_all_views()
        elif not self.dbc_manager.is_loaded():
            self.setWindowTitle("CANLab")

    def reset_all_views(self):
        """Rafraîchit les vues pour appliquer les informations du DBC aux données déjà reçues."""
        if self.is_monitoring:
            for msg_id, cache_entry in self.monitor_data_cache.items():
                cache_entry['comment'] = self.dbc_manager.get_message_name(msg_id)
            self.rx_table.setRowCount(0)
            self.monitor_id_to_row.clear()
            self._repopulate_monitor_from_cache()
        else:
            new_tracer_cache = []
            # L'ancien cache du traceur contient des messages, pas des tuples
            for msg in self.tracer_data_cache:
                # Vérifier si l'élément est un tuple ou un objet message
                if isinstance(msg, tuple):
                    can_msg = msg[0]
                else:
                    can_msg = msg
                name = self.dbc_manager.get_message_name(can_msg.arbitration_id)
                new_tracer_cache.append((can_msg, name))
            self.tracer_data_cache = new_tracer_cache
            self.rx_table.setRowCount(0)
            self._repopulate_tracer_from_cache()

    # --- HIGHLIGHT ---
    def highlight_row(self, row, duration_ms):
        """Met en surbrillance une ligne en rouge pour une durée donnée."""
        for col in range(self.rx_table.columnCount()):
            item = self.rx_table.item(row, col)
            if item:
                item.setBackground(QBrush(QColor("#FFCCCC"))) # Rouge clair
        QTimer.singleShot(duration_ms, lambda: self.unhighlight_row(row))

    def unhighlight_row(self, row):
        """Restaure la couleur de fond par défaut d'une ligne."""
        if row < self.rx_table.rowCount():
            # Utiliser la palette de base pour être compatible avec les thèmes et les lignes alternées
            default_brush = self.rx_table.palette().base()
            for col in range(self.rx_table.columnCount()):
                item = self.rx_table.item(row, col)
                if item:
                    item.setBackground(default_brush)

    def closeEvent(self, event): 
        self.disconnect_can(); event.accept()