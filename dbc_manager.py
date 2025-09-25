import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox

try:
    import cantools
except ImportError:
    cantools = None

class DBCManager:
    """Gère le chargement et l'interrogation de fichiers ou dossiers DBC."""
    def __init__(self):
        """Initialise le manager sans base de données chargée."""
        self.db = None
        self.source_name = None # Peut être un nom de fichier ou de dossier

    def _check_cantools(self, parent_widget):
        """Vérifie si la bibliothèque cantools est installée."""
        if cantools is None:
            QMessageBox.critical(parent_widget, "Bibliothèque manquante", 
                                 "La bibliothèque 'cantools' est requise pour cette fonctionnalité.\n"
                                 "Veuillez l'installer avec la commande : pip install cantools")
            return False
        return True

    def load_file(self, parent_widget):
        """Ouvre une boîte de dialogue pour sélectionner et charger UN SEUL fichier DBC."""
        if not self._check_cantools(parent_widget): return None

        path, _ = QFileDialog.getOpenFileName(parent_widget, "Load DBC File", "", "DBC Files (*.dbc)")
        if not path:
            return None

        try:
            self.db = cantools.database.load_file(path)
            self.source_name = os.path.basename(path)
            QMessageBox.information(parent_widget, "Succès", f"Fichier DBC '{self.source_name}' chargé avec succès.")
            return self.source_name
        except Exception as e:
            QMessageBox.critical(parent_widget, "Erreur de chargement DBC", f"Impossible de charger ou de parser le fichier DBC:\n{e}")
            self.db = None
            self.source_name = None
            return None

    def load_folder(self, parent_widget):
        """Ouvre une boîte de dialogue pour sélectionner un DOSSIER et fusionne tous les fichiers DBC trouvés."""
        if not self._check_cantools(parent_widget): return None

        path = QFileDialog.getExistingDirectory(parent_widget, "Select DBC Folder")
        if not path:
            return None

        try:
            dbc_files = [f for f in os.listdir(path) if f.lower().endswith('.dbc')]
            
            if not dbc_files:
                QMessageBox.warning(parent_widget, "Aucun fichier trouvé", f"Aucun fichier .dbc n'a été trouvé dans le dossier:\n{path}")
                return None

            merged_db = cantools.database.Database(strict=False)
            for file_name in dbc_files:
                file_path = os.path.join(path, file_name)
                merged_db.add_dbc_file(file_path)

            self.db = merged_db
            self.source_name = os.path.basename(path)
            QMessageBox.information(parent_widget, "Succès", 
                                    f"{len(dbc_files)} fichier(s) DBC du dossier '{self.source_name}' ont été chargés et fusionnés.")
            return self.source_name
        except Exception as e:
            QMessageBox.critical(parent_widget, "Erreur de chargement DBC", f"Une erreur est survenue lors de la fusion des fichiers DBC:\n{e}")
            self.db = None
            self.source_name = None
            return None

    def get_message_name(self, arbitration_id: int) -> str:
        """Récupère le nom d'un message CAN à partir de son ID."""
        if not self.db:
            return ""
        try:
            return self.db.get_message_by_frame_id(arbitration_id).name
        except KeyError:
            return ""

    def is_loaded(self) -> bool:
        """Vérifie si une base de données DBC est actuellement chargée."""
        return self.db is not None