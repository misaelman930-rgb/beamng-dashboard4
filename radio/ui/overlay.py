"""
Современный оверлей поверх игры в стиле автомобильного Now Playing.
Без рамки, полупрозрачный, перетаскиваемый.
Click-through пропускает клики в игру.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient, QBrush, QPainterPath
from PySide6.QtWidgets import (
    QLabel, QVBoxLayout, QWidget, QComboBox, QPushButton, QHBoxLayout, QFrame, QSlider
)

from .styles import ACCENT, ACCENT_DIM, MUTED, TEXT


class Overlay(QWidget):
    def __init__(self, settings):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                 | Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.settings = settings
        self._click_through = False
        self._drag: QPoint | None = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumWidth(380)
        self.setMaximumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # --- заголовок ---
        head = QHBoxLayout()
        self.hdr = QLabel("Now Playing")
        self.hdr.setStyleSheet(f"color:{MUTED}; font-size:12px; font-weight:500;")
        head.addWidget(self.hdr)
        head.addStretch(1)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        head.addWidget(self.info)
        root.addLayout(head)

        # --- основная зона: обложка + текст ---
        body = QHBoxLayout()
        body.setSpacing(14)

        # псевдо-обложка (градиент + буква)
        self.cover = QFrame()
        self.cover.setFixedSize(88, 88)
        self.cover.setObjectName("cover")
        self.cover.setStyleSheet(
            "QFrame#cover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #1a3a4a, stop:1 #0d1e28); border-radius: 14px; border: 1px solid #2a4050; }"
        )
        cover_lay = QVBoxLayout(self.cover)
        cover_lay.setContentsMargins(0, 0, 0, 0)
        self.cover_letter = QLabel("♪")
        self.cover_letter.setAlignment(Qt.AlignCenter)
        self.cover_letter.setStyleSheet(f"color:{ACCENT}; font-size:32px; font-weight:700; background:transparent;")
        cover_lay.addWidget(self.cover_letter)
        body.addWidget(self.cover)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.station = QLabel("—")
        self.station.setStyleSheet(f"color:{TEXT}; font-size:16px; font-weight:600;")
        self.station.setWordWrap(True)
        self.track = QLabel("")
        self.track.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        self.track.setWordWrap(True)
        text_col.addWidget(self.station)
        text_col.addWidget(self.track)
        text_col.addStretch(1)
        body.addLayout(text_col, 1)
        root.addLayout(body)

        # --- прогресс (визуальный, для стримов статичный) ---
        prog = QHBoxLayout()
        self.t_cur = QLabel("0:00")
        self.t_cur.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(35)
        self.slider.setEnabled(False)
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal { height:4px; background:#1e2a38; border-radius:2px; }"
            "QSlider::sub-page:horizontal { background:#4fc3f7; border-radius:2px; }"
            "QSlider::handle:horizontal { width:0px; }"
        )
        self.t_tot = QLabel("live")
        self.t_tot.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        prog.addWidget(self.t_cur)
        prog.addWidget(self.slider, 1)
        prog.addWidget(self.t_tot)
        root.addLayout(prog)

        # --- транспорт ---
        tr = QHBoxLayout()
        tr.setSpacing(10)
        self.b_prev = QPushButton("⏮")
        self.b_play = QPushButton("▶")
        self.b_next = QPushButton("⏭")
        for b, size in ((self.b_prev, 36), (self.b_play, 44), (self.b_next, 36)):
            b.setFixedSize(size, size)
            b.setCursor(Qt.PointingHandCursor)
        self.b_prev.setStyleSheet(self._btn_style(False))
        self.b_next.setStyleSheet(self._btn_style(False))
        self.b_play.setStyleSheet(self._btn_style(True))
        tr.addStretch(1)
        tr.addWidget(self.b_prev)
        tr.addWidget(self.b_play)
        tr.addWidget(self.b_next)
        tr.addStretch(1)
        root.addLayout(tr)

        # --- выбор станции (компактно) ---
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 4, 0, 0)
        self.station_picker = QComboBox()
        self.station_picker.setMinimumWidth(200)
        self.station_picker.setStyleSheet(
            "QComboBox { color:#e8eef4; background:#1a222d; padding:6px 10px; border:1px solid #2a3648; border-radius:10px; }"
            "QComboBox QAbstractItemView { color:#e8eef4; background:#1a222d; selection-background-color:#0288d1; border-radius:8px; }"
        )
        self.play_button = QPushButton("Включить")
        self.play_button.setStyleSheet(
            "QPushButton { color:#0a0e14; background:#4fc3f7; padding:6px 14px; border:0; border-radius:10px; font-weight:600; }"
            "QPushButton:hover { background:#81d4fa; }"
        )
        pick_row.addWidget(self.station_picker, 1)
        pick_row.addWidget(self.play_button)
        root.addLayout(pick_row)

        o = settings["overlay"]
        self.move(int(o["x"]), int(o["y"]))
        self.setWindowOpacity(float(o["opacity"]))
        self.set_click_through(bool(o["click_through"]))

    @staticmethod
    def _btn_style(primary: bool) -> str:
        if primary:
            return (
                "QPushButton { color:#0a0e14; background:#4fc3f7; border:0; border-radius:22px; font-size:16px; font-weight:700; }"
                "QPushButton:hover { background:#81d4fa; }"
            )
        return (
            "QPushButton { color:#e8eef4; background:#1a222d; border:1px solid #2a3648; border-radius:18px; font-size:14px; }"
            "QPushButton:hover { background:#243040; border-color:#4fc3f7; }"
        )

    # --- выбор станции ---
    def set_stations(self, stations, selected: str = "") -> None:
        self.station_picker.blockSignals(True)
        self.station_picker.clear()
        for sid, name in stations:
            self.station_picker.addItem(name, sid)
        index = self.station_picker.findData(selected)
        if index >= 0:
            self.station_picker.setCurrentIndex(index)
        self.station_picker.blockSignals(False)
        self.station_picker.setVisible(bool(stations))
        self.play_button.setVisible(bool(stations))
        self.adjustSize()

    def selected_station(self) -> str:
        return str(self.station_picker.currentData() or "")

    # --- данные ---
    def set_station(self, name: str) -> None:
        self.station.setText(name or "—")
        letter = (name or "♪")[0].upper()
        self.cover_letter.setText(letter if letter.isalnum() else "♪")
        self.adjustSize()

    def set_track(self, text: str) -> None:
        self.track.setText(text or "")
        self.track.setVisible(bool(text))
        self.adjustSize()

    def set_info(self, text: str) -> None:
        self.info.setText(text)

    def set_playing(self, playing: bool) -> None:
        self.b_play.setText("❚❚" if playing else "▶")

    def apply_opacity(self) -> None:
        self.setWindowOpacity(float(self.settings["overlay"]["opacity"]))

    # --- режимы ---
    def set_click_through(self, on: bool) -> None:
        self._click_through = on
        self.settings["overlay"]["click_through"] = on
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowTransparentForInput, on)
        if was_visible:
            self.show()

    def toggle_click_through(self) -> None:
        self.set_click_through(not self._click_through)

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
        self.settings["overlay"]["visible"] = self.isVisible()

    # --- отрисовка и перетаскивание ---
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        # тёмный градиентный фон как в скриншотах
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, QColor(12, 18, 28, 235))
        grad.setColorAt(1, QColor(8, 12, 20, 240))
        p.setBrush(QBrush(grad))
        pen = QPen(QColor(ACCENT_DIM if not self._click_through else "#1e2a38"), 1.5 if not self._click_through else 1.0)
        p.setPen(pen)
        p.drawRoundedRect(r, 18, 18)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:
        if self._drag is not None:
            self._drag = None
            self.settings["overlay"]["x"] = self.x()
            self.settings["overlay"]["y"] = self.y()
            self.settings.save()
