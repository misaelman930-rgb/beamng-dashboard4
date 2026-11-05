"""Тема в стиле автомобильной медиасистемы со скриншота (тёмный UI + cyan акценты)."""

ACCENT = "#4fc3f7"
ACCENT_DIM = "#0288d1"
BG = "#05080c"
PANEL = "#0e141c"
PANEL_2 = "#151c26"
TEXT = "#e8eef4"
MUTED = "#7a8899"
OK = "#26c6a0"
BAD = "#ef5350"
CARD = "#121820"
HIGHLIGHT = "#1a2430"
SIDEBAR = "#0a0e14"

MONO = "Segoe UI, Inter, system-ui, sans-serif"

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; font-family: {MONO}; }}
QDialog, QMainWindow {{ background: {BG}; }}
QLabel {{ background: transparent; }}

/* --- sidebar --- */
QFrame#sidebar {{
    background: {SIDEBAR};
    border: none;
    border-right: 1px solid #151c26;
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-radius: 12px;
    min-width: 44px;
    min-height: 44px;
    font-size: 18px;
    color: {MUTED};
}}
QPushButton#nav:hover {{ background: {HIGHLIGHT}; color: {TEXT}; }}
QPushButton#nav:checked {{
    background: #0d2a38;
    color: {ACCENT};
}}

/* --- cards --- */
QFrame#card {{
    background: {CARD};
    border: 1px solid #1a2430;
    border-radius: 20px;
}}
QFrame#coverCard {{
    background: {CARD};
    border: 1px solid #1a2430;
    border-radius: 16px;
}}
QFrame#nowCard {{
    background: {CARD};
    border: 1px solid #1a2430;
    border-radius: 18px;
}}

QLabel#title {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#bigTitle {{ color: {TEXT}; font-size: 18px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#accent {{ color: {ACCENT}; font-size: 13px; font-weight: 600; }}
QLabel#readout {{ color: {ACCENT}; font-size: 22px; font-weight: 700; }}
QLabel#readoutCap {{ color: {MUTED}; font-size: 11px; }}

QPushButton {{
    background: {PANEL_2};
    border: 1px solid #243040;
    border-radius: 12px;
    padding: 8px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {HIGHLIGHT}; border-color: {ACCENT_DIM}; }}
QPushButton:pressed {{ background: #1a2430; }}
QPushButton:checked {{ background: #0d2a38; border-color: {ACCENT}; color: {ACCENT}; }}

QPushButton#pill {{
    border-radius: 16px;
    padding: 8px 18px;
    background: transparent;
    border: 1px solid #2a3648;
    color: {MUTED};
}}
QPushButton#pill:checked {{
    background: {ACCENT};
    border: none;
    color: #0a0e14;
    font-weight: 600;
}}
QPushButton#pill:hover {{ border-color: {ACCENT}; color: {TEXT}; }}

QPushButton#transport {{
    font-size: 16px;
    min-width: 40px;
    min-height: 40px;
    border-radius: 20px;
    background: {PANEL_2};
    border: 1px solid #2a3648;
}}
QPushButton#play {{
    background: {ACCENT};
    color: #0a0e14;
    font-weight: 700;
    font-size: 18px;
    min-width: 48px;
    min-height: 48px;
    border-radius: 24px;
    border: none;
}}
QPushButton#play:hover {{ background: #81d4fa; }}

QPushButton#launch {{
    background: #0d2a38;
    border: 1px solid {ACCENT_DIM};
    color: {ACCENT};
    font-weight: 600;
    border-radius: 12px;
    padding: 8px 16px;
}}
QPushButton#launch:hover {{ background: #123a4c; }}

QListWidget {{
    background: transparent;
    border: none;
    outline: 0;
    padding: 4px;
}}
QListWidget::item {{
    padding: 10px 12px;
    border-radius: 12px;
    margin: 2px 0;
    color: {TEXT};
}}
QListWidget::item:selected {{
    background: #0d2a38;
    color: {ACCENT};
}}
QListWidget::item:hover {{ background: {HIGHLIGHT}; }}

QLineEdit, QComboBox {{
    background: {PANEL_2};
    border: 1px solid #243040;
    border-radius: 14px;
    padding: 8px 14px;
    color: {TEXT};
}}
QComboBox QAbstractItemView {{
    background: {PANEL_2};
    selection-background-color: #0d2a38;
    border-radius: 8px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT_DIM}; }}

QSlider::groove:horizontal {{
    height: 5px;
    background: #1e2a38;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: white;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QSlider::groove:vertical {{
    width: 6px;
    background: #1e2a38;
    border-radius: 3px;
}}
QSlider::sub-page:vertical {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background: white;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    padding: 8px 16px;
    color: {MUTED};
    border-radius: 12px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{ background: #0d2a38; color: {ACCENT}; }}

QCheckBox::indicator {{ width: 18px; height: 18px; }}
QToolTip {{
    background: {PANEL_2};
    color: {TEXT};
    border: 1px solid {ACCENT_DIM};
    border-radius: 8px;
    padding: 6px 10px;
}}
"""
