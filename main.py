import sys
from PyQt6.QtWidgets import QApplication
from can_lab_gui import CanLabGUI

if __name__ == '__main__':
    
    app = QApplication(sys.argv)
    main_win = CanLabGUI()
    main_win.show()
    sys.exit(app.exec())