"""Диалоги: настройки, редактор правил, добавление станции, поиск онлайн."""
from __future__ import annotations

import copy
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..hotkeys import validate_hotkey
from ..i18n import tr
from ..rules import ACTIONS, OPS, VARIABLES, WHILE_ACTIONS
from ..stations import GENRES, search_online

HOTKEY_ACTIONS = ["play_pause", "next", "prev", "vol_up", "vol_down", "mute",
                  "overlay", "click_through"]
HOTKEY_LABELS = {
    "play_pause": ("Play / Pause", "Играть / пауза"),
    "next": ("Next station", "Следующая станция"),
    "prev": ("Previous station", "Предыдущая станция"),
    "vol_up": ("Volume +", "Громкость +"),
    "vol_down": ("Volume −", "Громкость −"),
    "mute": ("Mute", "Без звука"),
    "overlay": ("Show/hide overlay", "Показать/скрыть оверлей"),
    "click_through": ("Overlay click-through", "Оверлей click-through"),
}


# =============================================================== добавить станцию
class AddStationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("add_station"))
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://host:port/stream  (.mp3 / .aac / .ogg / .pls / .m3u)")
        self.genre = QComboBox()
        self.genre.addItems([g for g in GENRES if g != "local"])
        form.addRow(tr("name"), self.name)
        form.addRow(tr("url"), self.url)
        form.addRow(tr("genre"), self.genre)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self):
        u = self.url.text().strip()
        if u.lower().startswith(("http://", "https://")):
            self.accept()
        else:
            self.url.setStyleSheet("border: 1px solid #ff5a52;")

    def values(self):
        return self.name.text().strip(), self.url.text().strip(), self.genre.currentText()


# =============================================================== поиск онлайн
class FindOnlineDialog(QDialog):
    """Поиск станций в каталоге radio-browser.info и добавление выбранных."""
    _done = Signal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("find_online"))
        self.resize(560, 460)
        self.results: list[dict] = []
        self.selected: list[dict] = []
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText(tr("search_hint"))
        self.q.returnPressed.connect(self._search)
        self.btn = QPushButton(tr("search"))
        self.btn.clicked.connect(self._search)
        row.addWidget(self.q, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._done.connect(self._show)

    def _search(self):
        text = self.q.text().strip()
        self.btn.setEnabled(False)
        self.status.setText("…")

        def work():
            try:
                # Одно слово пробуем и как тег, и как название.
                res = search_online(tag=text.lower()) if text and " " not in text else []
                if len(res) < 5:
                    res += [r for r in search_online(query=text) if r not in res]
                self._done.emit(res, "")
            except OSError as e:
                self._done.emit([], str(e))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, results: list, err: str):
        self.btn.setEnabled(True)
        self.results = results
        self.list.clear()
        self.status.setText(f"{tr('network_error')}: {err}" if err else f"{len(results)}")
        for r in results:
            extra = " · ".join(x for x in (r.get("codec"), f"{r.get('bitrate')} kbps" if r.get("bitrate") else "") if x)
            it = QListWidgetItem(f"{r['name']}   [{extra}]")
            it.setData(Qt.UserRole, r)
            self.list.addItem(it)

    def _ok(self):
        self.selected = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
        self.accept()


# =============================================================== редактор правил
class RulesDialog(QDialog):
    def __init__(self, rules: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("rules"))
        self.resize(820, 480)
        self.rules = copy.deepcopy(rules)
        self._cur = -1
        root = QVBoxLayout(self)
        hint = QLabel(tr("rules_hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        b_add, b_del = QPushButton(tr("add_rule")), QPushButton(tr("del_rule"))
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._del)
        left.addWidget(b_add)
        left.addWidget(b_del)
        body.addLayout(left, 1)

        form = QFormLayout()
        self.f_enabled = QCheckBox(tr("enabled"))
        self.f_name = QLineEdit()
        self.f_var = QComboBox(); self.f_var.addItems(VARIABLES)
        self.f_op = QComboBox(); self.f_op.addItems(list(OPS))
        self.f_val = QDoubleSpinBox(); self.f_val.setRange(-1e6, 1e6); self.f_val.setDecimals(2)
        self.f_for = QDoubleSpinBox(); self.f_for.setRange(0, 3600); self.f_for.setDecimals(1)
        self.f_act = QComboBox(); self.f_act.addItems(ACTIONS)
        self.f_param = QLineEdit()
        self.f_mode = QComboBox(); self.f_mode.addItems(["while", "once"])
        self.f_cool = QDoubleSpinBox(); self.f_cool.setRange(0, 3600); self.f_cool.setDecimals(1)
        self.f_act.currentTextChanged.connect(self._act_changed)
        form.addRow(self.f_enabled)
        form.addRow(tr("rule_name"), self.f_name)
        form.addRow(tr("variable"), self.f_var)
        form.addRow(tr("operator"), self.f_op)
        form.addRow(tr("value"), self.f_val)
        form.addRow(tr("for_s"), self.f_for)
        form.addRow(tr("action"), self.f_act)
        form.addRow(tr("param"), self.f_param)
        form.addRow(tr("mode"), self.f_mode)
        form.addRow(tr("cooldown"), self.f_cool)
        body.addLayout(form, 2)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._refill()

    # --- служебное ---
    def _act_changed(self, action: str):
        # Разовые действия не умеют режим while — блокируем выбор.
        can_while = action in WHILE_ACTIONS
        self.f_mode.setEnabled(can_while)
        if not can_while:
            self.f_mode.setCurrentText("once")

    def _refill(self, select: int = 0):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.rules:
            self.list.addItem(("✔ " if r.get("enabled", True) else "✖ ") + r.get("name", "?"))
        self.list.blockSignals(False)
        self._cur = -1
        if self.rules:
            self.list.setCurrentRow(min(select, len(self.rules) - 1))
            self._select(self.list.currentRow())
        else:
            self._set_form_enabled(False)

    def _set_form_enabled(self, on: bool):
        for w in (self.f_enabled, self.f_name, self.f_var, self.f_op, self.f_val,
                  self.f_for, self.f_act, self.f_param, self.f_mode, self.f_cool):
            w.setEnabled(on)

    def _commit(self):
        if not (0 <= self._cur < len(self.rules)):
            return
        r = self.rules[self._cur]
        r.update(name=self.f_name.text().strip() or "rule", enabled=self.f_enabled.isChecked(),
                 var=self.f_var.currentText(), op=self.f_op.currentText(), value=self.f_val.value(),
                 for_s=self.f_for.value(), action=self.f_act.currentText(),
                 param=self._param_value(), mode=self.f_mode.currentText(),
                 cooldown_s=self.f_cool.value())
        it = self.list.item(self._cur)
        if it:
            it.setText(("✔ " if r["enabled"] else "✖ ") + r["name"])

    def _param_value(self):
        text = self.f_param.text().strip()
        if self.f_act.currentText() in ("duck", "filter", "set_volume"):
            try:
                return float(text.replace(",", "."))
            except ValueError:
                return 0.5 if self.f_act.currentText() != "set_volume" else 50
        return text

    def _select(self, row: int):
        self._commit()
        self._cur = row
        if not (0 <= row < len(self.rules)):
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        r = self.rules[row]
        self.f_enabled.setChecked(r.get("enabled", True))
        self.f_name.setText(r.get("name", ""))
        self.f_var.setCurrentText(r.get("var", VARIABLES[0]))
        self.f_op.setCurrentText(r.get("op", ">"))
        self.f_val.setValue(float(r.get("value", 0)))
        self.f_for.setValue(float(r.get("for_s", 0)))
        self.f_act.setCurrentText(r.get("action", "duck"))
        self.f_param.setText(str(r.get("param", "")))
        self.f_mode.setCurrentText(r.get("mode", "while"))
        self.f_cool.setValue(float(r.get("cooldown_s", 0)))
        self._act_changed(self.f_act.currentText())

    def _add(self):
        self._commit()
        self.rules.append({"name": "New rule", "enabled": True, "var": "speed_kmh", "op": ">",
                           "value": 100, "for_s": 0.0, "action": "duck", "param": 0.5,
                           "mode": "while", "cooldown_s": 0.0})
        self._refill(len(self.rules) - 1)

    def _del(self):
        if 0 <= self._cur < len(self.rules):
            del self.rules[self._cur]
            self._cur = -1
            self._refill(max(0, self.list.currentRow()))

    def _save(self):
        self._commit()
        self.accept()


# =============================================================== настройки
class SettingsDialog(QDialog):
    def __init__(self, settings, audio, parent=None):
        super().__init__(parent)
        self.s = settings
        self.audio = audio
        self.setWindowTitle(tr("settings"))
        self.resize(620, 560)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        tabs.addTab(self._tab_general(), tr("general"))
        tabs.addTab(self._tab_effects(), tr("effects"))
        tabs.addTab(self._tab_hotkeys(), tr("hotkeys"))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # --- общие ---
    def _tab_general(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        self.lang = QComboBox(); self.lang.addItem("Русский", "ru"); self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(0 if self.s["language"] == "ru" else 1)
        self.port = QSpinBox(); self.port.setRange(1024, 65535); self.port.setValue(int(self.s["udp_port"]))
        self.autoplay = QCheckBox(); self.autoplay.setChecked(bool(self.s["autoplay"]))
        self.autoplay_engine = QCheckBox(); self.autoplay_engine.setChecked(bool(self.s.get("autoplay_on_engine", True)))
        self.device = QComboBox()
        btn = QPushButton(tr("refresh")); btn.clicked.connect(self._fill_devices)
        row = QHBoxLayout(); row.addWidget(self.device, 1); row.addWidget(btn)
        self.remote = QLineEdit(self.s["remote"]["url"])
        self.remote.setPlaceholderText("https://your-service.onrender.com")
        self.beamng_path = QLineEdit(self.s.data.get("beamng_path", "") or "")
        self.beamng_path.setPlaceholderText(r"C:\...\BeamNG.drive.x64.exe (пусто = авто)")
        self.opacity = QSlider(Qt.Horizontal); self.opacity.setRange(30, 100)
        self.opacity.setValue(int(self.s["overlay"]["opacity"] * 100))
        f.addRow(tr("language"), self.lang)
        f.addRow(tr("udp_port"), self.port)
        f.addRow(tr("audio_device"), row)
        f.addRow("Autoplay", self.autoplay)
        f.addRow("Оверлей при запуске двигателя", self.autoplay_engine)
        f.addRow(tr("beamng_path"), self.beamng_path)
        f.addRow(tr("remote_server"), self.remote)
        f.addRow(tr("overlay") + " α", self.opacity)
        self._fill_devices()
        return w

    def _fill_devices(self):
        self.device.clear()
        self.device.addItem(tr("default_device"), "")
        if self.audio:
            for did, desc in self.audio.list_devices():
                if did:
                    self.device.addItem(desc, did)
        idx = self.device.findData(self.s["audio_device"])
        self.device.setCurrentIndex(max(0, idx))

    # --- эффекты ---
    def _tab_effects(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        # громкость от скорости
        sv = self.s["speed_volume"]
        self.sv_on = QCheckBox(tr("speed_volume")); self.sv_on.setChecked(sv["enabled"])
        lay.addWidget(self.sv_on)
        lay.addWidget(QLabel(tr("curve")))
        self.curve = QTableWidget(0, 2)
        self.curve.setHorizontalHeaderLabels(["km/h", "%"])
        self.curve.horizontalHeader().setStretchLastSection(True)
        for kmh, g in sorted(sv["curve"]):
            self._curve_row(kmh, g * 100)
        lay.addWidget(self.curve, 1)
        row = QHBoxLayout()
        a, d = QPushButton(tr("add_point")), QPushButton(tr("del_point"))
        a.clicked.connect(lambda: self._curve_row(100, 80))
        d.clicked.connect(lambda: self.curve.removeRow(self.curve.currentRow()) if self.curve.rowCount() > 1 else None)
        row.addWidget(a); row.addWidget(d); row.addStretch(1)
        lay.addLayout(row)
        # фильтр
        cf = self.s["car_filter"]
        self.cf_on = QCheckBox(tr("car_filter")); self.cf_on.setChecked(cf["enabled"])
        self.cf_str = QSlider(Qt.Horizontal); self.cf_str.setRange(0, 100); self.cf_str.setValue(int(cf["strength"] * 100))
        self.cf_rpm = QSpinBox(); self.cf_rpm.setRange(1000, 20000); self.cf_rpm.setSingleStep(500); self.cf_rpm.setValue(int(cf["rpm_max"]))
        lay.addWidget(self.cf_on)
        f = QFormLayout(); f.addRow(tr("strength"), self.cf_str); f.addRow(tr("rpm_max"), self.cf_rpm)
        lay.addLayout(f)
        # автожанр
        ag = self.s["auto_genre"]
        self.ag_on = QCheckBox(tr("auto_genre")); self.ag_on.setChecked(ag["enabled"])
        self.ag_calm = QComboBox(); self.ag_calm.addItems(GENRES[:6]); self.ag_calm.setCurrentText(ag["calm_genre"])
        self.ag_en = QComboBox(); self.ag_en.addItems(GENRES[:6]); self.ag_en.setCurrentText(ag["energetic_genre"])
        self.ag_lo = QSpinBox(); self.ag_lo.setRange(0, 400); self.ag_lo.setValue(int(ag["calm_below_kmh"]))
        self.ag_hi = QSpinBox(); self.ag_hi.setRange(0, 400); self.ag_hi.setValue(int(ag["energetic_above_kmh"]))
        self.ag_int = QSpinBox(); self.ag_int.setRange(10, 3600); self.ag_int.setValue(int(ag["min_interval_s"]))
        lay.addWidget(self.ag_on)
        f2 = QFormLayout()
        f2.addRow(tr("calm_genre"), self.ag_calm); f2.addRow(tr("calm_below"), self.ag_lo)
        f2.addRow(tr("energetic_genre"), self.ag_en); f2.addRow(tr("energetic_above"), self.ag_hi)
        f2.addRow(tr("min_interval"), self.ag_int)
        lay.addLayout(f2)
        return w

    def _curve_row(self, kmh, pct):
        r = self.curve.rowCount()
        self.curve.insertRow(r)
        self.curve.setItem(r, 0, QTableWidgetItem(str(int(kmh))))
        self.curve.setItem(r, 1, QTableWidgetItem(str(int(pct))))

    # --- горячие клавиши ---
    def _tab_hotkeys(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        f.addRow(QLabel(tr("hotkey_hint")))
        self.hk: dict[str, QLineEdit] = {}
        ru = tr("enabled") == "Включено"
        for a in HOTKEY_ACTIONS:
            e = QLineEdit(self.s["hotkeys"].get(a, ""))
            self.hk[a] = e
            f.addRow(HOTKEY_LABELS[a][1 if ru else 0], e)
        return w

    # --- сохранение ---
    def _save(self):
        # проверка горячих клавиш
        bad = False
        for e in self.hk.values():
            ok = (not e.text().strip()) or validate_hotkey(e.text().strip())
            e.setStyleSheet("" if ok else "border: 1px solid #ff5a52;")
            bad = bad or not ok
        if bad:
            return
        s = self.s
        s["language"] = self.lang.currentData()
        s["udp_port"] = self.port.value()
        s["autoplay"] = self.autoplay.isChecked()
        s["autoplay_on_engine"] = self.autoplay_engine.isChecked()
        s["beamng_path"] = self.beamng_path.text().strip()
        remote_url = self.remote.text().strip()
        if remote_url and not remote_url.lower().startswith(("http://", "https://")):
            self.remote.setStyleSheet("border: 1px solid #ff5a52;")
            return
        s["remote"] = {"url": remote_url, "interval_s": self.s["remote"]["interval_s"]}
        s["audio_device"] = self.device.currentData() or ""
        s["overlay"]["opacity"] = self.opacity.value() / 100.0
        curve = []
        for r in range(self.curve.rowCount()):
            try:
                curve.append([float(self.curve.item(r, 0).text()),
                              max(0.0, min(1.5, float(self.curve.item(r, 1).text()) / 100.0))])
            except (ValueError, AttributeError):
                continue
        s["speed_volume"] = {"enabled": self.sv_on.isChecked(), "curve": curve or [[0, 1.0]]}
        s["car_filter"] = {"enabled": self.cf_on.isChecked(), "strength": self.cf_str.value() / 100.0,
                           "rpm_max": self.cf_rpm.value()}
        s["auto_genre"] = {"enabled": self.ag_on.isChecked(), "calm_genre": self.ag_calm.currentText(),
                           "energetic_genre": self.ag_en.currentText(),
                           "calm_below_kmh": self.ag_lo.value(), "energetic_above_kmh": self.ag_hi.value(),
                           "min_interval_s": self.ag_int.value()}
        s["hotkeys"] = {a: e.text().strip() for a, e in self.hk.items()}
        self.accept()
