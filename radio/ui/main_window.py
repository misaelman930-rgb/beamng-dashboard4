"""Главное окно — дизайн как на скриншоте автомобильной медиасистемы."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QSlider,
    QVBoxLayout, QWidget, QMessageBox, QLineEdit, QButtonGroup, QSizePolicy,
)

from ..controller import Controller
from ..i18n import tr
from ..stations import GENRES
from .dialogs import AddStationDialog, FindOnlineDialog, RulesDialog, SettingsDialog
from .overlay import Overlay
from .styles import BAD, OK, ACCENT, MUTED, TEXT


def _card(name="card") -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


class MainWindow(QMainWindow):
    def __init__(self, ctrl: Controller):
        super().__init__()
        self.ctrl = ctrl
        self.settings = ctrl.settings
        self.store = ctrl.store
        self.overlay = Overlay(self.settings)
        w = self.settings["window"]
        self.resize(int(w.get("w", 1180)), int(w.get("h", 720)))
        self.setMinimumSize(960, 600)
        self._build()
        self._connect()
        self.overlay.play_button.clicked.connect(self._overlay_play_station)
        self.overlay.b_prev.clicked.connect(ctrl.prev_station)
        self.overlay.b_next.clicked.connect(ctrl.next_station)
        self.overlay.b_play.clicked.connect(ctrl.toggle_play)
        self.retranslate()
        self.refresh_list()
        self._on_conn(False, "")
        self.on_volume(self.settings["volume"], self.settings["muted"])
        if ctrl.audio_error:
            self.status_line.setText(tr("vlc_missing"))
        if self.settings["overlay"]["visible"]:
            self.overlay.show()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ========== LEFT SIDEBAR ==========
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(64)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(8, 16, 8, 16)
        sb.setSpacing(6)

        logo = QLabel("BNG")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"color:{ACCENT}; font-weight:800; font-size:13px; letter-spacing:1px;")
        sb.addWidget(logo)
        sb.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_icons = [
            ("home", "⌂"),
            ("music", "♫"),
            ("car", "▣"),
            ("lock", "🔒"),
            ("fan", "❄"),
            ("light", "☀"),
            ("settings", "⚙"),
        ]
        self.nav_btns = {}
        for key, icon in nav_icons:
            b = QPushButton(icon)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(key)
            self.nav_group.addButton(b)
            self.nav_btns[key] = b
            sb.addWidget(b)
        self.nav_btns["music"].setChecked(True)
        sb.addStretch(1)
        user_btn = QPushButton("👤")
        user_btn.setObjectName("nav")
        sb.addWidget(user_btn)
        outer.addWidget(sidebar)

        # ========== MAIN CONTENT ==========
        main = QVBoxLayout()
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(14)
        outer.addLayout(main, 1)

        # --- top bar: profile + search + launch ---
        top = QHBoxLayout()
        top.setSpacing(12)

        profile = QHBoxLayout()
        avatar = QLabel("📻")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background:#1a2a38; border-radius:18px; font-size:16px; border:1px solid #2a4050;"
        )
        profile.addWidget(avatar)
        prof_text = QVBoxLayout()
        prof_text.setSpacing(0)
        self.l_app_name = QLabel("BeamNG Radio")
        self.l_app_name.setObjectName("title")
        self.l_conn = QLabel("")
        self.l_conn.setObjectName("muted")
        prof_text.addWidget(self.l_app_name)
        prof_text.addWidget(self.l_conn)
        profile.addLayout(prof_text)
        top.addLayout(profile)

        top.addSpacing(16)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a station…")
        self.search.setMinimumWidth(220)
        self.search.setMaximumWidth(360)
        top.addWidget(self.search, 1)

        self.b_launch = QPushButton("▶  BeamNG")
        self.b_launch.setObjectName("launch")
        self.b_launch.setCursor(Qt.PointingHandCursor)
        top.addWidget(self.b_launch)

        self.b_overlay = QPushButton("Overlay")
        self.b_overlay.setCheckable(True)
        self.b_rules = QPushButton("Rules")
        self.b_settings = QPushButton("⚙")
        self.b_settings.setFixedWidth(40)
        for b in (self.b_overlay, self.b_rules, self.b_settings):
            top.addWidget(b)
        main.addLayout(top)

        # --- tabs: Music / Playlists / … ---
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_btns = {}
        for key, label in (("music", "Music"), ("fav", "Favorites"), ("local", "Local"), ("online", "Online")):
            b = QPushButton(label)
            b.setObjectName("pill")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b)
            self.tab_btns[key] = b
            tabs.addWidget(b)
        self.tab_btns["music"].setChecked(True)
        tabs.addStretch(1)
        main.addLayout(tabs)

        # --- middle: album covers row + right cards ---
        mid = QHBoxLayout()
        mid.setSpacing(14)

        # left: featured + station list
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        # featured covers row
        covers_row = QHBoxLayout()
        covers_row.setSpacing(12)
        self.cover_cards = []
        for i in range(4):
            c = _card("coverCard")
            c.setFixedSize(150, 150)
            cl = QVBoxLayout(c)
            cl.setContentsMargins(0, 0, 0, 0)
            letter = QLabel("♪")
            letter.setAlignment(Qt.AlignCenter)
            letter.setStyleSheet(
                f"font-size:42px; font-weight:700; color:{ACCENT}; "
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a3a4a,stop:1 #0d1e28); "
                f"border-radius:16px;"
            )
            cl.addWidget(letter)
            covers_row.addWidget(c)
            self.cover_cards.append((c, letter))
        covers_row.addStretch(1)
        left_col.addLayout(covers_row)

        # station list
        list_card = _card("card")
        ll = QVBoxLayout(list_card)
        ll.setContentsMargins(12, 10, 12, 10)
        hdr = QHBoxLayout()
        self.l_stations_hdr = QLabel("Stations")
        self.l_stations_hdr.setObjectName("title")
        hdr.addWidget(self.l_stations_hdr)
        hdr.addStretch(1)
        self.filter = QComboBox()
        self.filter.setMinimumWidth(120)
        hdr.addWidget(self.filter)
        ll.addLayout(hdr)
        self.list = QListWidget()
        self.list.setMinimumHeight(160)
        ll.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.b_add = QPushButton("＋ Add")
        self.b_del = QPushButton("Remove")
        self.b_fav = QPushButton("★")
        self.b_fav.setFixedWidth(40)
        self.b_local = QPushButton("Local files")
        self.b_find = QPushButton("Find online")
        for b in (self.b_add, self.b_del, self.b_fav, self.b_local, self.b_find):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        ll.addLayout(btn_row)
        left_col.addWidget(list_card, 1)
        mid.addLayout(left_col, 5)

        # right column: battery-style cards + telemetry
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # connection / status card
        st_card = _card("card")
        stl = QVBoxLayout(st_card)
        stl.setContentsMargins(14, 12, 14, 12)
        self.dot = QLabel("●")
        self.conn_text = QLabel("")
        row = QHBoxLayout()
        row.addWidget(self.dot)
        row.addWidget(self.conn_text, 1)
        stl.addLayout(row)
        self.l_status_extra = QLabel("")
        self.l_status_extra.setObjectName("muted")
        stl.addWidget(self.l_status_extra)
        right_col.addWidget(st_card)

        # telemetry card
        tele = _card("card")
        g = QGridLayout(tele)
        g.setContentsMargins(12, 12, 12, 12)
        g.setSpacing(8)
        self.readouts = {}
        self.caps = {}
        for i, key in enumerate(("speed", "rpm", "gear", "fuel", "temp")):
            val = QLabel("--")
            val.setObjectName("readout")
            val.setAlignment(Qt.AlignCenter)
            cap = QLabel()
            cap.setObjectName("readoutCap")
            cap.setAlignment(Qt.AlignCenter)
            g.addWidget(val, 0, i)
            g.addWidget(cap, 1, i)
            self.readouts[key], self.caps[key] = val, cap
        right_col.addWidget(tele)

        # volume card (circular feel)
        vol_card = _card("card")
        vl = QVBoxLayout(vol_card)
        vl.setContentsMargins(14, 12, 14, 12)
        vl.setAlignment(Qt.AlignCenter)
        vol_lbl = QLabel("Volume")
        vol_lbl.setObjectName("title")
        vol_lbl.setAlignment(Qt.AlignCenter)
        vl.addWidget(vol_lbl)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        vl.addWidget(self.slider)
        vol_row = QHBoxLayout()
        self.b_mute = QPushButton("🔇")
        self.b_mute.setCheckable(True)
        self.b_mute.setFixedWidth(40)
        self.l_vol = QLabel("70")
        self.l_vol.setObjectName("accent")
        self.l_vol.setAlignment(Qt.AlignCenter)
        vol_row.addWidget(self.b_mute)
        vol_row.addWidget(self.l_vol, 1)
        vl.addLayout(vol_row)
        right_col.addWidget(vol_card)

        right_col.addStretch(1)
        mid.addLayout(right_col, 2)
        main.addLayout(mid, 1)

        # ========== BOTTOM NOW PLAYING BAR ==========
        now = _card("nowCard")
        now.setFixedHeight(88)
        nl = QHBoxLayout(now)
        nl.setContentsMargins(16, 10, 16, 10)
        nl.setSpacing(14)

        self.cover_mini = QLabel("♪")
        self.cover_mini.setFixedSize(64, 64)
        self.cover_mini.setAlignment(Qt.AlignCenter)
        self.cover_mini.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a3a4a,stop:1 #0d1e28);"
            f"border-radius:12px; font-size:26px; font-weight:700; color:{ACCENT}; border:1px solid #2a4050;"
        )
        nl.addWidget(self.cover_mini)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        self.l_station = QLabel("—")
        self.l_station.setObjectName("bigTitle")
        self.l_track = QLabel("")
        self.l_track.setObjectName("muted")
        self.l_state = QLabel("")
        self.l_state.setObjectName("accent")
        meta.addWidget(self.l_station)
        meta.addWidget(self.l_track)
        meta.addWidget(self.l_state)
        nl.addLayout(meta, 1)

        # transport
        tr = QHBoxLayout()
        tr.setSpacing(8)
        self.b_prev = QPushButton("⏮")
        self.b_prev.setObjectName("transport")
        self.b_play = QPushButton("▶")
        self.b_play.setObjectName("play")
        self.b_next = QPushButton("⏭")
        self.b_next.setObjectName("transport")
        for b in (self.b_prev, self.b_play, self.b_next):
            tr.addWidget(b)
        nl.addLayout(tr)

        # progress-ish
        prog = QVBoxLayout()
        self.l_rules = QLabel("")
        self.l_rules.setObjectName("muted")
        prog.addWidget(self.l_rules)
        nl.addLayout(prog)

        main.addWidget(now)

        self.status_line = QLabel("")
        self.status_line.setObjectName("muted")
        main.addWidget(self.status_line)

    def _connect(self) -> None:
        c = self.ctrl
        # клик и двойной клик по станции — воспроизведение
        self.list.itemClicked.connect(self._play_list_item)
        self.list.itemDoubleClicked.connect(self._play_list_item)
        self.filter.currentIndexChanged.connect(lambda _=0: self.refresh_list())
        self.search.textChanged.connect(self._on_search)
        self.b_add.clicked.connect(self._add_station)
        self.b_del.clicked.connect(self._remove_station)
        self.b_fav.clicked.connect(self._toggle_fav)
        self.b_local.clicked.connect(self._add_local)
        self.b_find.clicked.connect(self._find_online)
        self.b_prev.clicked.connect(lambda: c.prev_station())
        self.b_next.clicked.connect(lambda: c.next_station())
        self.b_play.clicked.connect(lambda: c.toggle_play())
        self.b_mute.clicked.connect(lambda _=False: c.toggle_mute())
        self.slider.valueChanged.connect(c.set_volume)
        self.b_overlay.clicked.connect(self._toggle_overlay)
        self.b_rules.clicked.connect(self._open_rules)
        self.b_settings.clicked.connect(self._open_settings)
        self.b_launch.clicked.connect(self._launch_beamng)

        self.tab_btns["music"].clicked.connect(lambda: self._set_filter_mode("all"))
        self.tab_btns["fav"].clicked.connect(lambda: self._set_filter_mode("fav"))
        self.tab_btns["local"].clicked.connect(lambda: self._set_filter_mode("local"))
        self.tab_btns["online"].clicked.connect(self._find_online)

        # обложки кликабельны
        for i, (card, _letter) in enumerate(self.cover_cards):
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = (lambda e, idx=i: self._play_cover(idx))

        c.tick.connect(self.on_tick)
        c.connectionChanged.connect(self._on_conn)
        c.trackChanged.connect(self.on_track)
        c.stationsChanged.connect(self.refresh_list)
        c.stationChanged.connect(self.on_station)
        c.engineStarted.connect(self._show_engine_overlay)
        c.statusChanged.connect(self.on_status)
        c.message.connect(self._on_message)
        c.volumeChanged.connect(self.on_volume)
        c.overlayToggle.connect(self._toggle_overlay_hotkey)
        c.clickThroughToggle.connect(self.overlay.toggle_click_through)

        # сразу показать, если VLC нет
        if c.audio_error:
            self.status_line.setText(
                "VLC не найден — звук не будет работать. Установите VLC 64-bit с videolan.org"
            )
            self.l_status_extra.setText("Нужен VLC 64-bit")
        # URL панели для телефона
        dash = getattr(c, "_dashboard", None)
        if dash and getattr(dash, "urls", None):
            self.l_status_extra.setText("Телефон: " + dash.urls[0])
            if not c.audio_error:
                self.status_line.setText("Открой на телефоне: " + "  |  ".join(dash.urls))

    def _set_filter_mode(self, mode: str) -> None:
        if mode == "fav":
            idx = self.filter.findData("fav")
        elif mode == "local":
            idx = self.filter.findData("all")
        else:
            idx = self.filter.findData("all")
        if idx >= 0:
            self.filter.setCurrentIndex(idx)
        self.refresh_list()

    def _on_search(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            name = it.text().lower()
            it.setHidden(bool(text) and text not in name)

    def _play_list_item(self, item) -> None:
        if item is None:
            return
        sid = item.data(Qt.UserRole)
        if sid:
            self.status_line.setText(f"Запуск: {item.text()}…")
            self.ctrl.play_station(sid)

    def _play_cover(self, idx: int) -> None:
        playable = [s for s in self.store.stations if s.playable]
        if 0 <= idx < len(playable):
            self.status_line.setText(f"Запуск: {playable[idx].name}…")
            self.ctrl.play_station(playable[idx].id)

    def _on_message(self, text: str) -> None:
        self.status_line.setText(text or "")
        if text:
            self.l_status_extra.setText(text[:60])

    # ---------- launch BeamNG ----------
    def _launch_beamng(self) -> None:
        path = ""
        try:
            path = (self.settings["beamng_path"] or "").strip()
        except Exception:
            path = ""
        candidates = []
        if path:
            candidates.append(path)
        home = os.path.expanduser("~")
        candidates.extend([
            r"C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe",
            r"C:\Program Files\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe",
            os.path.join(home, r"Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe"),
            r"C:\Program Files\Epic Games\BeamNG.drive\Bin64\BeamNG.drive.x64.exe",
        ])
        for p in candidates:
            if p and os.path.isfile(p):
                try:
                    subprocess.Popen([p], cwd=os.path.dirname(p))
                    self.status_line.setText("BeamNG.drive запускается…")
                    return
                except OSError as e:
                    self.status_line.setText(f"Не удалось запустить: {e}")
                    return
        try:
            if sys.platform.startswith("win"):
                os.startfile("steam://rungameid/284160")
            else:
                subprocess.Popen(["xdg-open", "steam://rungameid/284160"])
            self.status_line.setText("Запуск через Steam…")
        except Exception:
            QMessageBox.information(
                self, "BeamNG",
                "Не найден exe BeamNG.drive.\n\n"
                "Укажите путь в Настройки → путь к BeamNG.drive.exe\n"
                "или запустите игру вручную (Steam: steam://rungameid/284160)."
            )

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app_title"))
        self.b_overlay.setText(tr("overlay"))
        self.b_rules.setText(tr("rules"))
        self.b_add.setText("＋ " + tr("add_station"))
        self.b_del.setText(tr("remove_station"))
        self.b_local.setText(tr("add_local"))
        self.b_find.setText(tr("find_online"))
        self.b_launch.setText("▶  " + tr("launch_beamng"))
        self.l_stations_hdr.setText(tr("stations"))
        for key, cap in (("speed", "km/h"), ("rpm", "RPM"), ("gear", tr("gear")),
                         ("fuel", tr("fuel") + " %"), ("temp", "°C")):
            self.caps[key].setText(cap)
        cur = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem(tr("all"), "all")
        self.filter.addItem(tr("favorites"), "fav")
        for g in GENRES:
            self.filter.addItem(g.capitalize(), g)
        self.filter.setCurrentIndex(max(0, self.filter.findData(cur)))
        self.filter.blockSignals(False)
        self._on_conn(self.ctrl.connected, "")
        self.refresh_list()

    def refresh_list(self) -> None:
        mode = self.filter.currentData() or "all"
        cur_id = self.ctrl.current.id if self.ctrl.current else None
        self.list.clear()
        ids = []
        playable = [s for s in self.store.stations if s.playable]
        for s in playable:
            if mode == "fav" and not s.favorite:
                continue
            if mode not in ("all", "fav") and s.genre != mode:
                continue
            it = QListWidgetItem(("★ " if s.favorite else "") + s.name)
            it.setData(Qt.UserRole, s.id)
            it.setToolTip(s.url or ", ".join(s.local_files))
            self.list.addItem(it)
            ids.append(s.id)
            if s.id == cur_id:
                self.list.setCurrentItem(it)
        self.ctrl.set_queue(ids)
        # update cover cards with first stations
        for i, (card, letter) in enumerate(self.cover_cards):
            if i < len(playable):
                s = playable[i]
                letter.setText((s.name[0] if s.name else "♪").upper())
                card.setToolTip(s.name)
            else:
                letter.setText("♪")
                card.setToolTip("")

    def _selected_id(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _add_station(self) -> None:
        d = AddStationDialog(self)
        if d.exec():
            name, url, genre = d.values()
            self.store.add(name, url, genre)
            self.refresh_list()

    def _remove_station(self) -> None:
        sid = self._selected_id()
        if sid:
            self.store.remove(sid)
            self.refresh_list()

    def _toggle_fav(self) -> None:
        sid = self._selected_id()
        if sid:
            self.store.toggle_favorite(sid)
            self.refresh_list()

    def _add_local(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("local_files"), "", "Audio (*.mp3 *.flac *.wav *.ogg *.aac *.m4a)")
        if files:
            st = self.store.add_local(files)
            self.refresh_list()
            self.ctrl.play_station(st.id)

    def _find_online(self) -> None:
        d = FindOnlineDialog(self)
        if d.exec():
            for r in d.selected:
                self.store.add(r["name"], r["url"], "other")
            self.refresh_list()

    def on_station(self, sid: str) -> None:
        self.overlay.set_stations(
            [(st.id, st.name) for st in self.store.stations if st.playable], sid)
        st = self.store.get(sid)
        name = st.name if st else "—"
        self.l_station.setText(name)
        self.overlay.set_station(name)
        letter = (name or "♪")[0].upper()
        self.cover_mini.setText(letter if letter.isalnum() else "♪")
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == sid:
                self.list.setCurrentRow(i)
                break

    def on_track(self, text: str) -> None:
        self.l_track.setText(text or tr("no_track"))
        self.overlay.set_track(text)

    def on_status(self, st: str) -> None:
        icon = {"playing": "▶", "paused": "❚❚", "stopped": "■"}.get(st)
        text = {"buffering": tr("buffering"), "retrying": tr("stream_error")}.get(st, icon or "")
        self.l_state.setText(text)
        playing = st in ("playing", "buffering", "retrying")
        self.b_play.setText("❚❚" if playing else "▶")
        self.overlay.set_playing(playing)

    def on_volume(self, vol: int, muted: bool) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(vol)
        self.slider.blockSignals(False)
        self.l_vol.setText(str(vol))
        self.b_mute.setChecked(muted)

    def _on_conn(self, ok: bool, msg: str) -> None:
        if msg.startswith("port_error"):
            self.dot.setStyleSheet(f"color:{BAD}; font-size:16px;")
            self.conn_text.setText(f"{tr('port_error')} ({self.settings['udp_port']})")
            self.l_conn.setText(tr("port_error"))
            self.l_status_extra.setText(
                f"Порт {self.settings['udp_port']} занят. Закройте другое приложение или смените порт в Настройках."
            )
            return
        self.dot.setStyleSheet(f"color:{OK if ok else ACCENT}; font-size:16px;")
        self.conn_text.setText(tr("connected") if ok else tr("waiting"))
        self.l_conn.setText(tr("connected") if ok else tr("waiting"))
        if ok:
            self.l_status_extra.setText("OutGauge OK — телеметрия идёт")
        else:
            self.l_status_extra.setText(
                "Включите OutGauge в игре: Options → Other → Protocols → OutGauge "
                f"(IP 127.0.0.1, порт {self.settings['udp_port']}), затем сядьте в машину."
            )
            for k in self.readouts:
                self.readouts[k].setText("--")

    def on_tick(self, t, active: list) -> None:
        if t:
            gear = {0: "R", 1: "N"}.get(t.gear, str(t.gear - 1))
            self.readouts["speed"].setText(f"{t.speed_kmh:.0f}")
            self.readouts["rpm"].setText(f"{t.rpm:.0f}")
            self.readouts["gear"].setText(gear)
            self.readouts["fuel"].setText(f"{t.fuel * 100:.0f}")
            self.readouts["temp"].setText(f"{t.engine_temp:.0f}")
            self.overlay.set_info(f"{t.speed_kmh:.0f} km/h · {gear} · {t.rpm:.0f} rpm")
        else:
            self.overlay.set_info("")
        self.l_rules.setText((tr("now_rules") + ": " + ", ".join(active)) if active else "")

    def _overlay_play_station(self) -> None:
        sid = self.overlay.selected_station()
        if sid:
            self.ctrl.play_station(sid)

    def _show_engine_overlay(self) -> None:
        self.overlay.set_stations(
            [(st.id, st.name) for st in self.store.stations if st.playable],
            self.settings["last_station"])
        self.overlay.show()
        self.settings["overlay"]["visible"] = True
        self.b_overlay.setChecked(True)
        if self.settings["autoplay_on_engine"] and self.settings["last_station"]:
            st = self.ctrl.audio.status() if self.ctrl.audio else ""
            if st not in ("playing", "buffering"):
                self.ctrl.play_station(self.settings["last_station"])

    def _toggle_overlay(self) -> None:
        self.overlay.toggle_visible()
        self.b_overlay.setChecked(self.overlay.isVisible())

    def _toggle_overlay_hotkey(self) -> None:
        self._toggle_overlay()

    def _open_rules(self) -> None:
        d = RulesDialog(self.settings["rules"], self)
        if d.exec():
            self.settings["rules"] = d.rules
            self.ctrl.reload_rules()
            self.settings.save()

    def _open_settings(self) -> None:
        d = SettingsDialog(self.settings, self.ctrl.audio, self)
        if d.exec():
            self.ctrl.apply_settings()
            self.overlay.apply_opacity()
            self.retranslate()

    def closeEvent(self, e) -> None:
        self.settings["window"] = {"w": self.width(), "h": self.height()}
        self.settings["overlay"]["visible"] = self.overlay.isVisible()
        self.overlay.close()
        self.ctrl.shutdown()
        e.accept()
        QApplication.quit()
