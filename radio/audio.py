"""
Аудио-движок на python-vlc (libvlc).

Почему VLC: умеет всё из требований «из коробки» — HTTP/Icecast/Shoutcast,
mp3/aac/ogg/flac/wav, ICY-метаданные, выбор устройства вывода, 10-полосный
эквалайзер (на нём строится эффект «радио в машине»), переподключение.

Важно про потоки: VLC вызывает события из СВОЕГО потока. Из колбэков нельзя
вызывать stop()/play() (дедлок), поэтому колбэки только ставят флаги, а всю
работу делает poll(), который вызывается из таймера Qt (главный поток).
"""
from __future__ import annotations

import math
import re
import struct
import time
import urllib.request
import wave
from pathlib import Path
from typing import Callable, Optional

MAX_RETRIES = 3                      # попыток переподключения до «станция мертва»
STALL_TIMEOUT = 25.0                 # буферизация дольше — считаем сбоем
UA = {"User-Agent": "BeamNGRadio/1.0"}

# Центры полос 10-полосного эквалайзера VLC: 60,170,310,600,1k,3k,6k,12k,14k,16k Гц.
# Усиление (дБ) при strength=1: «узкая полоса» — режем низ и особенно верх.
_EQ_TABLE = [-10.0, -4.0, 0.0, 2.0, 2.0, -6.0, -12.0, -20.0, -20.0, -20.0]
_EQ_PREAMP = -2.0


class AudioUnavailable(RuntimeError):
    """VLC / libvlc не найден."""


def resolve_playlist(url: str, timeout: float = 6.0) -> str:
    """
    .pls и .m3u — это не поток, а список ссылок. Достаём первый адрес.
    HLS (.m3u8) и прямые потоки возвращаем как есть.
    """
    low = url.lower().split("?", 1)[0]
    if not (low.endswith(".pls") or low.endswith(".m3u")):
        return url
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(65536).decode("utf-8", "ignore")
    except Exception:       # noqa: BLE001 — отдаём исходный URL, пусть VLC попробует сам
        return url
    if low.endswith(".pls"):
        m = re.search(r"^File\d+=(\S+)", text, re.M | re.I)
        return m.group(1) if m else url
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return url


def ensure_blip(path: Path) -> Path:
    """Создаёт короткий «джингл» (два тона) в WAV, если файла ещё нет."""
    if path.exists():
        return path
    rate = 22050
    frames = bytearray()
    for freq, dur in ((880.0, 0.11), (1318.5, 0.16)):
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / (rate * 0.01)) * (1.0 - i / n) ** 1.5   # атака+спад
            frames += struct.pack("<h", int(14000 * env * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


class AudioEngine:
    """Обёртка над libvlc. Все публичные методы вызываются из главного потока."""

    def __init__(self, on_event: Optional[Callable[[str, object], None]] = None,
                 blip_path: Optional[Path] = None):
        try:
            import vlc                                   # type: ignore
        except Exception as e:                           # noqa: BLE001 (OSError/NameError/ImportError)
            raise AudioUnavailable(str(e)) from e
        self.vlc = vlc
        self.instance = vlc.Instance("--no-video", "--quiet", "--intf=dummy",
                                     "--network-caching=2500", "--http-reconnect")
        if self.instance is None:
            raise AudioUnavailable("libvlc instance could not be created")
        self.player = self.instance.media_player_new()
        self.jingle_player = self.instance.media_player_new()
        self.on_event = on_event or (lambda kind, data=None: None)
        self.blip_path = blip_path

        # состояние
        self.mode = "none"                # "stream" | "files" | "none"
        self.url = ""
        self.files: list[str] = []
        self.file_index = 0
        self.user_paused = False
        self.track = ""
        self.volume = 70                  # эффективная громкость 0..100 (уже со всеми множителями)
        self.muted = False
        self.device = ""                  # id устройства; "" = по умолчанию

        # служебное
        self._ended = False
        self._error = False
        self._fail_count = 0
        self._retry_at = 0.0
        self._play_started = 0.0
        self._state_since = time.monotonic()
        self._last_state = None
        self._last_meta_poll = 0.0
        self._last_dev_poll = 0.0
        self._known_devices: Optional[set] = None
        self._eq = None
        self._eq_strength = -1.0

        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._cb_error)
        em.event_attach(vlc.EventType.MediaPlayerEndReached, self._cb_end)

    # ------------------------------------------------------------ колбэки VLC
    def _cb_error(self, _e):
        self._error = True

    def _cb_end(self, _e):
        self._ended = True

    # ------------------------------------------------------------ воспроизведение
    def play_url(self, url: str) -> None:
        """Запускает интернет-поток (URL уже разрешён, не плейлист)."""
        self.mode, self.url, self.files = "stream", url, []
        self.user_paused = False
        self._fail_count = 0
        self._start_current()

    def play_files(self, files: list[str]) -> None:
        """Запускает очередь локальных файлов."""
        self.mode, self.url, self.files, self.file_index = "files", "", list(files), 0
        self.user_paused = False
        self._fail_count = 0
        self._start_current()

    def _start_current(self) -> None:
        self._ended = self._error = False
        self._retry_at = 0.0
        self.track = ""
        if self.mode == "stream":
            media = self.instance.media_new(self.url)
        elif self.mode == "files" and self.files:
            media = self.instance.media_new_path(self.files[self.file_index])
        else:
            return
        self.player.set_media(media)
        self._apply_device()
        self.player.audio_set_volume(int(self.volume))
        self.player.audio_set_mute(self.muted)
        self.player.play()
        self._play_started = time.monotonic()
        self._state_since = time.monotonic()
        self._last_meta_poll = 0.0

    def stop(self) -> None:
        self.mode = "none"
        self._retry_at = 0.0
        self.player.stop()
        self.track = ""

    def pause(self) -> None:
        """Для потоков — stop (при возобновлении звук будет «живым», а не из буфера)."""
        if self.mode == "none" or self.user_paused:
            return
        self.user_paused = True
        if self.mode == "files":
            self.player.set_pause(1)
        else:
            self.player.stop()

    def resume(self) -> None:
        if self.mode == "none" or not self.user_paused:
            return
        self.user_paused = False
        if self.mode == "files":
            self.player.set_pause(0)
        else:
            self._fail_count = 0
            self._start_current()

    def toggle(self) -> None:
        if self.user_paused:
            self.resume()
        else:
            self.pause()

    @property
    def is_active(self) -> bool:
        return self.mode != "none" and not self.user_paused

    # ------------------------------------------------------------ громкость и фильтр
    def set_volume(self, volume: float) -> None:
        v = max(0, min(100, int(round(volume))))
        if v != self.volume:                    # вызывается 10 раз/с — не дёргаем VLC зря
            self.volume = v
            self.player.audio_set_volume(v)

    def set_muted(self, muted: bool) -> None:
        if muted != self.muted:
            self.muted = muted
            self.player.audio_set_mute(muted)

    def set_filter_strength(self, strength: float) -> None:
        """
        «Радио в машине»: через эквалайзер VLC срезаем верха и низы и чуть
        поднимаем середину. strength 0..1; 0 — эффект выключен.
        Обновляем только при заметном изменении, чтобы не дёргать VLC.
        """
        strength = max(0.0, min(1.0, strength))
        if abs(strength - self._eq_strength) < 0.03 and not (strength == 0.0 and self._eq_strength != 0.0):
            return
        self._eq_strength = strength
        try:
            if strength <= 0.0:
                try:
                    self.player.set_equalizer(None)          # NULL = выключить эквалайзер
                    self._eq = None
                    return
                except Exception:                            # noqa: BLE001
                    pass                                     # запасной путь: плоская кривая ниже
            eq = self.vlc.AudioEqualizer()
            bands = min(len(_EQ_TABLE), self.vlc.libvlc_audio_equalizer_get_band_count())
            for i in range(bands):
                eq.set_amp_at_index(_EQ_TABLE[i] * strength, i)
            eq.set_preamp(_EQ_PREAMP * strength)
            self.player.set_equalizer(eq)
            self._eq = eq                      # держим ссылку, чтобы GC не освободил
        except Exception:                      # noqa: BLE001 — эквалайзер опционален
            pass

    # ------------------------------------------------------------ джингл
    def play_jingle(self, path: str = "") -> None:
        """Короткий звук поверх радио. Пустой path — встроенный сигнал."""
        file = path if path and Path(path).exists() else (str(self.blip_path) if self.blip_path else "")
        if not file:
            return
        try:
            self.jingle_player.set_media(self.instance.media_new_path(file))
            self.jingle_player.audio_set_volume(85)
            self.jingle_player.play()
        except Exception:                      # noqa: BLE001
            pass

    # ------------------------------------------------------------ устройства вывода
    def list_devices(self) -> list[tuple[str, str]]:
        """[(id, описание)]. Пустой id — «по умолчанию»."""
        out: list[tuple[str, str]] = []
        try:
            head = self.player.audio_output_device_enum()
            node = head
            while node:
                dev = node.contents
                did = dev.device.decode("utf-8", "ignore") if dev.device else ""
                desc = dev.description.decode("utf-8", "ignore") if dev.description else did
                out.append((did, desc))
                node = dev.next
            if head:
                self.vlc.libvlc_audio_output_device_list_release(head)
        except Exception:                      # noqa: BLE001
            pass
        return out

    def set_device(self, device_id: str) -> None:
        self.device = device_id or ""
        self._apply_device()

    def _apply_device(self) -> None:
        if self.device:
            try:
                self.player.audio_output_device_set(None, self.device.encode("utf-8"))
            except Exception:                  # noqa: BLE001
                pass

    # ------------------------------------------------------------ метаданные
    def _read_track(self) -> str:
        media = self.player.get_media()
        if not media:
            return ""
        M = self.vlc.Meta
        now = media.get_meta(M.NowPlaying)           # ICY StreamTitle
        if now:
            return now
        if self.mode == "files":
            artist, title = media.get_meta(M.Artist), media.get_meta(M.Title)
            if title:
                return f"{artist} — {title}" if artist else title
            return Path(self.files[self.file_index]).stem
        return ""

    # ------------------------------------------------------------ главный цикл
    def poll(self) -> None:
        """Вызывать ~2 раза в секунду из главного потока."""
        now = time.monotonic()

        # 1) конец файла → следующий; конец потока → сбой
        if self._ended:
            self._ended = False
            if self.mode == "files" and not self.user_paused:
                self.file_index = (self.file_index + 1) % len(self.files)
                self._start_current()
            elif self.mode == "stream" and not self.user_paused:
                self._error = True

        # 2) ошибки и переподключение с нарастающей задержкой
        if self._error and self.mode != "none" and not self.user_paused:
            self._error = False
            self._fail_count += 1
            if self._fail_count > MAX_RETRIES:
                self.on_event("dead", self.url or (self.files[self.file_index] if self.files else ""))
                self.stop()
                return
            self._retry_at = now + 2 ** self._fail_count
            self.player.stop()
            self.on_event("error", self._fail_count)
        if self._retry_at and now >= self._retry_at:
            self._retry_at = 0.0
            if self.mode == "files":                    # битый файл — пропускаем
                self.file_index = (self.file_index + 1) % len(self.files)
            self._start_current()

        # 3) «зависание» буферизации
        if self.mode != "none" and not self.user_paused and not self._retry_at:
            state = self.player.get_state()
            if state != self._last_state:
                self._last_state = state
                self._state_since = now
            S = self.vlc.State
            if state in (S.Opening, S.Buffering) and now - self._state_since > STALL_TIMEOUT:
                self._error = True
            if state == S.Error:
                self._error = True
            if state == S.Playing and now - self._play_started > 5.0:
                self._fail_count = 0                    # стабильно играет — сбрасываем счётчик

        # 4) ICY-метаданные раз в 2 с
        if now - self._last_meta_poll > 2.0 and self.mode != "none":
            self._last_meta_poll = now
            try:
                t = self._read_track()
            except Exception:                           # noqa: BLE001
                t = self.track
            if t != self.track:
                self.track = t
                self.on_event("track", t)

        # 5) смена аудиоустройства раз в 5 с
        if now - self._last_dev_poll > 5.0:
            self._last_dev_poll = now
            self._check_devices()

    def _check_devices(self) -> None:
        ids = {d for d, _ in self.list_devices()}
        if not ids:
            return
        if self._known_devices is not None and ids != self._known_devices:
            vanished = bool(self.device) and self.device not in ids
            if vanished:
                self.device = ""                        # выбранное устройство пропало → системное
                self.on_event("device", "fallback")
            elif not self.device:
                self.on_event("device", "changed")      # системное могло смениться
            if (vanished or not self.device) and self.is_active:
                self._known_devices = ids
                self._start_current()                   # перезапуск вывода на новое устройство
                return
        self._known_devices = ids

    def status(self) -> str:
        """Статус для UI: stopped | paused | retrying | buffering | playing."""
        if self.mode == "none":
            return "stopped"
        if self.user_paused:
            return "paused"
        if self._retry_at:
            return "retrying"
        S = self.vlc.State
        st = self.player.get_state()
        if st in (S.Opening, S.Buffering):
            return "buffering"
        return "playing" if st == S.Playing else "buffering"

    def shutdown(self) -> None:
        try:
            self.player.stop()
            self.jingle_player.stop()
            self.player.release()
            self.jingle_player.release()
            self.instance.release()
        except Exception:                               # noqa: BLE001
            pass
