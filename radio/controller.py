"""
Контроллер: связывает телеметрию, правила, аудио, станции и настройки.

Главный цикл — таймер Qt на 100 мс (10 Гц): этого достаточно для плавной
громкости и почти не грузит CPU. Поток OutGauge только кладёт последний
пакет в listener.last — никакой работы на каждый пакет (BeamNG шлёт их
десятки раз в секунду).
"""
from __future__ import annotations

import random
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .audio import AudioEngine, ensure_blip, resolve_playlist
from .hotkeys import HotkeyManager
from .i18n import set_language, tr
from .remote import RemoteSync
from .rules import RuleEngine, interp_curve
from .settings import Settings, config_dir
from .stations import Station, StationStore
from .telemetry import Telemetry, TelemetryListener


class Controller(QObject):
    # --- сигналы для UI ---
    tick = Signal(object, list)            # (Telemetry | None, [активные правила])
    connectionChanged = Signal(bool, str)  # (подключено, сообщение)
    trackChanged = Signal(str)
    stationChanged = Signal(str)           # id станции
    statusChanged = Signal(str)            # play/pause/buffering...
    message = Signal(str)                  # короткие сообщения в статус-строку
    volumeChanged = Signal(int, bool)      # (базовая громкость, mute)
    overlayToggle = Signal()
    clickThroughToggle = Signal()
    stationsChanged = Signal()
    engineStarted = Signal()
    _resolved = Signal(int, str)           # (токен запроса, URL или "")
    _hotkey = Signal(str)                  # из потока pynput
    _conn = Signal(bool, str)              # из потока UDP
    _remote = Signal(object, str)          # из потока синхронизации: (станции | None, ошибка)

    def __init__(self, settings: Settings, store: StationStore):
        super().__init__()
        self.settings = settings
        self.store = store
        set_language(settings["language"])

        # --- аудио (может быть недоступно, если не установлен VLC) ---
        self.audio: Optional[AudioEngine] = None
        self.audio_error = ""
        try:
            blip = ensure_blip(config_dir() / "blip.wav")
            self.audio = AudioEngine(on_event=self._audio_event, blip_path=blip)
            self.audio.set_device(settings["audio_device"])
        except Exception as e:             # noqa: BLE001 — любой сбой VLC не должен валить запуск
            self.audio = None
            self.audio_error = str(e) or type(e).__name__

        # --- состояние ---
        self.current: Optional[Station] = None
        self.queue_ids: list[str] = []
        self.connected = False
        self.last_telemetry: Optional[Telemetry] = None
        self._token = 0
        self._dead_in_row = 0
        self._vol_smooth: Optional[float] = None
        self._rule_paused = False
        self._rule_pause_override = False
        self._jingle_until = 0.0
        self._zone: Optional[str] = None
        self._last_genre_switch = 0.0
        self._tick_n = 0
        self._last_status = ""
        self._engine_was_on = False

        # --- правила ---
        self.rules = RuleEngine(settings["rules"], on_action=self._rule_action)

        # --- телеметрия ---
        self.listener = TelemetryListener(
            port=int(settings["udp_port"]), host=settings["udp_host"],
            on_status=lambda ok, msg: self._conn.emit(ok, msg))
        self._conn.connect(self._on_conn)
        self.listener.start()

        # --- горячие клавиши ---
        self.hotkeys = HotkeyManager(emit=self._hotkey.emit)
        self._hotkey.connect(self.handle_action)
        self.hotkeys.apply(settings["hotkeys"])

        self._resolved.connect(self._on_resolved)
        self._sync: Optional[RemoteSync] = None
        self._rotation: Optional[dict] = None
        self.car_profiles: dict = settings["car_profiles"]
        self.now_track = ""
        self._profile_dirty = False
        self._profile_saved = 0.0
        self._sync_url = ""
        self._dashboard = None
        self._remote.connect(self._on_remote)
        self.set_queue([])

        # --- таймеры ---
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(100)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start(500)

    # ------------------------------------------------------------ старт/стоп
    def start(self) -> None:
        """Автозапуск последней станции, синхронизация и телефонная панель."""
        self.start_remote_sync()
        self.start_dashboard()
        if self.settings["autoplay"] and self.settings["last_station"]:
            self.play_station(self.settings["last_station"])
        elif self.settings["last_station"]:
            self.current = self.store.get(self.settings["last_station"])
            if self.current:
                self.stationChanged.emit(self.current.id)

    def start_dashboard(self) -> None:
        """HTTP-панель для телефона (SimDashboard-style)."""
        try:
            from .dashboard_server import DashboardServer
            port = int(self.settings.get("dashboard_port", 8765) or 8765)
            self._dashboard = DashboardServer(self, port=port)
            self._dashboard.start()
            if self._dashboard.urls:
                urls = "  ·  ".join(self._dashboard.urls)
                self.message.emit(f"Телефон: {urls}")
        except Exception as e:
            self._dashboard = None
            self.message.emit(f"Dashboard: {e}")

    def start_remote_sync(self) -> None:
        """Запускает (или перезапускает) опрос сервера станций по настройкам."""
        from .remote import normalize_server_url
        rc = self.settings["remote"]
        try:
            url = normalize_server_url(rc["url"])
        except ValueError:
            self.message.emit(tr("remote_bad_url"))
            url = ""
        if url == self._sync_url and (self._sync is not None or not url):
            return
        if self._sync:
            self._sync.stop()
            self._sync = None
        self._sync_url = url
        if url:
            self._sync = RemoteSync(url, rc["interval_s"],
                                    on_result=lambda items, err: self._remote.emit(items, err))
            self._sync.start()

    def _on_remote(self, items, err: str) -> None:
        if items is None:
            self.message.emit(tr("remote_error") + f" ({err})")
            return
        if self.store.merge_remote(items):
            self.set_queue([])
            self.stationsChanged.emit()

    def shutdown(self) -> None:
        if self._sync:
            self._sync.stop()
        if self._dashboard:
            try:
                self._dashboard.stop()
            except Exception:
                pass
            self._dashboard = None
        self._timer.stop()
        self._poll_timer.stop()
        self.hotkeys.stop()
        self.listener.stop()
        if self.audio:
            self.audio.shutdown()
        self.settings.save()
        self.store.save()

    # ------------------------------------------------------------ станции
    def set_queue(self, ids: list[str]) -> None:
        """Порядок для next/prev (UI передаёт отображаемый список)."""
        if ids:
            self.queue_ids = ids
        else:
            self.queue_ids = [s.id for s in self.store.stations
                              if s.playable]

    def play_station(self, sid: str) -> None:
        st = self.store.get(sid)
        if not st:
            return
        self.current = st
        self.settings["last_station"] = sid
        self.stationChanged.emit(sid)
        self.now_track = ""
        self.trackChanged.emit("")
        self._rotation = None
        if st.rotate:
            # Своё радио: играем по очереди станции из списка, переключая каждые rotate_min минут.
            self._rotation = {"station": st, "idx": 0, "next": time.monotonic() + st.rotate_min * 60}
            first = self.store.get(st.rotate[0])
            if first:
                self._load(first, shown=st)
            return
        self._load(st, shown=st)

    def _load(self, st: Station, shown: Station) -> None:
        """Запускает станцию st (URL/файлы). shown — то, что видит пользователь."""
        if not self.audio:
            self.message.emit(tr("vlc_missing"))
            return
        self._token += 1
        token = self._token
        self._rule_paused = False
        if st.is_local:
            self.audio.play_files(st.local_files)
            self._after_play()
            return
        self.message.emit(tr("buffering"))
        if shown is not st:
            self.now_track = st.name
            self.trackChanged.emit(st.name)

        def work():                    # сеть — в фоне, чтобы не вешать UI
            url = ""
            if self.store.ensure_url(st) and st.url:
                url = resolve_playlist(st.url)
            self._resolved.emit(token, url)

        threading.Thread(target=work, daemon=True).start()

    def _rotate_tick(self, now: float) -> None:
        """Переключает станцию в ротации по таймеру, с джинглом."""
        rot = self._rotation
        if not rot or now < rot["next"] or self.audio is None:
            return
        ids = rot["station"].rotate
        rot["idx"] = (rot["idx"] + 1) % len(ids)
        rot["next"] = now + rot["station"].rotate_min * 60
        nxt = self.store.get(ids[rot["idx"]])
        if nxt:
            self.audio.play_jingle()
            self._load(nxt, shown=rot["station"])

    def _on_resolved(self, token: int, url: str) -> None:
        if token != self._token or not self.audio:
            return                     # пользователь уже выбрал другую станцию
        if not url:
            self.message.emit(tr("stream_error"))
            self._dead_in_row += 1
            self._skip_dead()
            return
        self.audio.play_url(url)
        self._after_play()

    def _after_play(self) -> None:
        self.audio.set_muted(self.settings["muted"])
        self._vol_smooth = None        # громкость применится на ближайшем тике
        self.statusChanged.emit(self.audio.status())

    def _step(self, delta: int) -> None:
        if not self.queue_ids:
            self.set_queue([])
        if not self.queue_ids:
            return
        cur = self.current.id if self.current else None
        idx = self.queue_ids.index(cur) if cur in self.queue_ids else -1
        self.play_station(self.queue_ids[(idx + delta) % len(self.queue_ids)])

    def next_station(self) -> None:
        self._dead_in_row = 0
        self._step(+1)

    def prev_station(self) -> None:
        self._dead_in_row = 0
        self._step(-1)

    def _skip_dead(self) -> None:
        """Станция не отвечает — идём к следующей, но не бесконечно."""
        if self._dead_in_row >= max(2, len(self.queue_ids)):
            self._dead_in_row = 0
            self.message.emit(tr("stream_error"))
            return
        self.message.emit(tr("skip_dead"))
        self._step(+1)

    def switch_genre(self, genre: str) -> None:
        cands = [s for s in self.store.by_genre(genre) if not self.current or s.id != self.current.id]
        if cands:
            self.play_station(random.choice(cands).id)

    # ------------------------------------------------------------ транспорт
    def toggle_play(self) -> None:
        if not self.audio:
            self.message.emit(tr("vlc_missing"))
            return
        if self.audio.mode == "none":
            if self.current:
                self.play_station(self.current.id)
            elif self.queue_ids:
                self.play_station(self.queue_ids[0])
            else:
                first = next((st for st in self.store.stations if st.playable), None)
                if first:
                    self.play_station(first.id)
                else:
                    self.message.emit("Нет станций — добавьте или найдите онлайн")
            return
        if self._rule_paused:                     # пользователь перебил автопаузу
            self._rule_paused = False
            self._rule_pause_override = True
            self.audio.resume()
        else:
            self.audio.toggle()
        self.statusChanged.emit(self.audio.status())

    def set_volume(self, v: int) -> None:
        self.settings["volume"] = max(0, min(100, int(v)))
        self.volumeChanged.emit(self.settings["volume"], self.settings["muted"])

    def toggle_mute(self) -> None:
        self.settings["muted"] = not self.settings["muted"]
        self.volumeChanged.emit(self.settings["volume"], self.settings["muted"])

    def handle_action(self, name: str) -> None:
        """Единая точка для горячих клавиш и кнопок."""
        if name == "play_pause":
            self.toggle_play()
        elif name == "next":
            self.next_station()
        elif name == "prev":
            self.prev_station()
        elif name == "vol_up":
            self.set_volume(self.settings["volume"] + 5)
        elif name == "vol_down":
            self.set_volume(self.settings["volume"] - 5)
        elif name == "mute":
            self.toggle_mute()
        elif name == "overlay":
            self.overlayToggle.emit()
        elif name == "click_through":
            self.clickThroughToggle.emit()

    # ------------------------------------------------------------ правила
    def _rule_action(self, action: str, param) -> None:
        """Разовые действия движка правил."""
        if action == "next":
            self.next_station()
        elif action == "prev":
            self.prev_station()
        elif action == "genre" and param:
            self.switch_genre(str(param))
        elif action == "jingle" and self.audio:
            self.audio.play_jingle(str(param or ""))
            self._jingle_until = time.monotonic() + 1.4   # приглушим радио на время джингла
        elif action == "set_volume":
            try:
                self.set_volume(int(float(param)))
            except (TypeError, ValueError):
                pass

    def reload_rules(self) -> None:
        self.rules.set_rules(self.settings["rules"])

    # ------------------------------------------------------------ телеметрия
    def _on_conn(self, ok: bool, msg: str) -> None:
        self.connected = ok
        if not ok:
            self.last_telemetry = None
        self.connectionChanged.emit(ok, msg)

    def apply_network_settings(self) -> None:
        port = int(self.settings["udp_port"])
        if port != self.listener.port:
            self.listener.set_port(port)

    # ------------------------------------------------------------ главный тик (10 Гц)
    def _on_tick(self) -> None:
        now = time.monotonic()
        t = self.listener.last if self.listener.connected else None
        self.last_telemetry = t
        if t:
            from .car_profile import learn
            if learn(self.car_profiles, t.car, t.speed_kmh, t.rpm):
                self._profile_dirty = True
        if self._profile_dirty and now - self._profile_saved > 10:
            self._profile_dirty = False
            self._profile_saved = now
            self.settings["car_profiles"] = self.car_profiles
            self.settings.save()
        fx = self.rules.evaluate(t.variables() if t else None, now)
        s = self.settings

        # Автозапуск радио при первом появлении работающего двигателя.
        engine_on = bool(t and not t.engine_off)
        if not engine_on:
            self._engine_was_on = False
        elif not self._engine_was_on:
            self._engine_was_on = True
            if s.get("autoplay_on_engine", True):
                self.engineStarted.emit()
                if self.audio and self.audio.mode == "none":
                    sid = s["last_station"]
                    if not sid or not self.store.get(sid) or not self.store.get(sid).playable:
                        first = next((st for st in self.store.stations if st.playable), None)
                        sid = first.id if first else ""
                    if sid:
                        self.play_station(sid)

        if self.audio:
            # ---- громкость: база × кривая скорости × приглушение правил ----
            gain = 1.0
            sv = s["speed_volume"]
            if t and sv["enabled"]:
                gain = interp_curve(sv["curve"], t.speed_kmh)
            duck = fx.duck
            if now < self._jingle_until:
                duck = min(duck, 0.4)
            target = max(0.0, min(100.0, s["volume"] * gain * duck))
            if self._vol_smooth is None:
                self._vol_smooth = target
            else:                                  # сглаживание, чтобы не «щёлкало»
                self._vol_smooth += (target - self._vol_smooth) * 0.25
            self.audio.set_volume(self._vol_smooth)
            self.audio.set_muted(bool(s["muted"] or fx.mute))

            # ---- автопауза по правилам ----
            if fx.pause:
                if not self._rule_paused and not self._rule_pause_override and self.audio.is_active:
                    self.audio.pause()
                    self._rule_paused = True
                    self.statusChanged.emit(self.audio.status())
            else:
                self._rule_pause_override = False
                if self._rule_paused:
                    self._rule_paused = False
                    self.audio.resume()
                    self.statusChanged.emit(self.audio.status())

            # ---- эффект «радио в машине» ----
            cf = s["car_filter"]
            strength = 0.0
            if cf["enabled"]:
                load = min(1.0, t.rpm / max(1.0, float(cf["rpm_max"]))) if t else 0.0
                strength = float(cf["strength"]) * (0.25 + 0.75 * load)
            strength = max(strength, fx.filter_boost)
            self.audio.set_filter_strength(strength)

            # ---- автосмена жанра ----
            self._auto_genre(t, now)

        self._rotate_tick(now)

        # ---- обновление UI примерно 5 раз в секунду ----
        self._tick_n += 1
        if self._tick_n % 2 == 0:
            self.tick.emit(t, self.rules.active_rules())

    def _auto_genre(self, t: Optional[Telemetry], now: float) -> None:
        ag = self.settings["auto_genre"]
        if not (ag["enabled"] and t and self.audio and self.audio.is_active):
            return
        kmh = t.speed_kmh
        if kmh < float(ag["calm_below_kmh"]):
            zone, genre = "calm", ag["calm_genre"]
        elif kmh > float(ag["energetic_above_kmh"]):
            zone, genre = "energetic", ag["energetic_genre"]
        else:
            return                                  # гистерезис: между порогами ничего не меняем
        if zone == self._zone:
            return
        if now - self._last_genre_switch < float(ag["min_interval_s"]):
            return
        self._zone = zone
        self._last_genre_switch = now
        if not self.current or self.current.genre != genre:
            self.switch_genre(genre)

    # ------------------------------------------------------------ аудио-события и опрос
    def _on_poll(self) -> None:
        if self.audio:
            self.audio.poll()
            st = self.audio.status()
            if st != self._last_status:
                self._last_status = st
                self.statusChanged.emit(st)

    def _audio_event(self, kind: str, data) -> None:
        if kind == "track":
            self.now_track = str(data)
            self.trackChanged.emit(str(data))
            self._dead_in_row = 0
        elif kind == "error":
            self.message.emit(tr("stream_error"))
        elif kind == "dead":
            self._dead_in_row += 1
            self._skip_dead()
        elif kind == "device":
            self.message.emit(tr("device_changed"))

    # ------------------------------------------------------------ применение настроек
    def apply_settings(self) -> None:
        """Вызывается после закрытия диалога настроек."""
        set_language(self.settings["language"])
        self.reload_rules()
        self.apply_network_settings()
        self.start_remote_sync()
        bad = self.hotkeys.apply(self.settings["hotkeys"])
        if bad:
            self.message.emit("Hotkey error: " + ", ".join(bad))
        if self.audio and self.audio.device != self.settings["audio_device"]:
            self.audio.set_device(self.settings["audio_device"])
            if self.audio.is_active:
                self.audio._start_current()        # перезапуск, чтобы применилось устройство
        self._zone = None
        self.settings.save()
