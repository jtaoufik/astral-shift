"""Shared look: warm peach panels, coral accent."""

ACCENT = "#e8442a"
INK = "#3a2a28"

QSS = f"""
QDialog {{ background: transparent; color: {INK}; font-size: 13px; }}
QPushButton#Close {{
    background: rgba(0,0,0,0.08); border: none; border-radius: 11px; padding: 0;
    font-size: 11px; color: #6b4f46;
}}
QPushButton#Close:hover {{ background: {ACCENT}; color: white; }}
QFrame#Card {{ background: rgba(255,255,255,0.55); border: 1px solid rgba(255,255,255,0.8); border-radius: 12px; }}
QListWidget {{ background: rgba(255,255,255,0.55); border: 1px solid rgba(255,255,255,0.8); border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: rgba(232,68,42,0.18); color: {INK}; }}
QKeySequenceEdit, QComboBox {{ background: white; border: 1px solid rgba(0,0,0,0.12); border-radius: 6px; padding: 3px 6px; }}
QLabel {{ color: {INK}; background: transparent; }}
QLabel#Title {{ font-size: 15px; font-weight: 600; }}
QLabel#Muted {{ color: #8a6d63; font-size: 12px; }}
QPushButton {{
    background: rgba(255,255,255,0.75); border: 1px solid rgba(0,0,0,0.08);
    border-radius: 7px; padding: 5px 12px; color: {INK};
}}
QPushButton:hover {{ background: white; }}
QPushButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 6px 16px; }}
QPushButton#Primary:hover {{ background: #f05a3f; }}
QPushButton#Primary:disabled {{ background: #e9b3a6; }}
QPushButton#Chip {{ padding: 3px 10px; border-radius: 6px; font-size: 12px; }}
QPushButton#Swatch {{ border-radius: 6px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; }}
QPushButton#Swatch:checked {{ border: 2px solid {INK}; }}
QSlider::groove:horizontal {{ height: 4px; background: rgba(0,0,0,0.12); border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; border: 1px solid rgba(0,0,0,0.2); width: 14px; margin: -6px 0; border-radius: 7px; }}
QLineEdit, QSpinBox {{ background: white; border: 1px solid rgba(0,0,0,0.12); border-radius: 6px; padding: 3px 6px; }}
QTableWidget {{ background: rgba(255,255,255,0.8); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; gridline-color: rgba(0,0,0,0.06); }}
QHeaderView::section {{ background: transparent; border: none; font-weight: 600; padding: 4px; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid rgba(0,0,0,0.25); background: rgba(255,255,255,0.85); }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
"""
