"""
Список станций: стартовый набор, пользовательские станции, избранное, поиск онлайн.

Стартовые станции делятся на два типа:
  * с прямым URL (SomaFM, Radio Paradise, BBC World Service);
  * с «resolve»: URL подбирается при первом запуске через открытый каталог
    radio-browser.info по тегу (например phonk). Так мы не храним устаревшие
    ссылки на станции, которые часто меняют адрес потока.
Найденный URL кэшируется в stations.json.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from .settings import config_dir

GENRES = ["rock", "electronic", "phonk", "retro", "jazz", "news", "chanson", "russian", "local", "other"]

RB_SERVERS = ["https://de1.api.radio-browser.info", "https://nl1.api.radio-browser.info",
              "https://at1.api.radio-browser.info"]
UA = {"User-Agent": "BeamNGRadio/1.0"}


@dataclass
class Station:
    id: str
    name: str
    url: str = ""
    genre: str = "other"
    favorite: bool = False
    builtin: bool = False
    resolve_tag: str = ""      # если url пуст — подобрать по тегу radio-browser
    local_files: list = field(default_factory=list)   # для «станции» из файлов
    remote: bool = False       # пришла с сервера станций (нельзя удалить локально)
    resolve_query: str = ""    # подобрать URL по названию в radio-browser
    rotate: list = field(default_factory=list)   # своё радио: ids станций для ротации
    rotate_min: int = 15       # через сколько минут переключать в ротации

    @property
    def playable(self) -> bool:
        """Есть ли что играть: прямой URL, файлы, подбор по каталогу или ротация."""
        return bool(self.url or self.is_local or self.resolve_tag or self.resolve_query or self.rotate)

    @property
    def is_local(self) -> bool:
        return bool(self.local_files)


def _b(sid, name, url, genre, tag=""):
    return Station(id=sid, name=name, url=url, genre=genre, builtin=True, resolve_tag=tag)


def _q(sid, name, query, genre):
    """Станция, URL которой подбирается по названию в каталоге radio-browser."""
    return Station(id=sid, name=name, genre=genre, builtin=True, resolve_query=query)


def builtin_stations() -> list[Station]:
    return [
        # Шансон
        _q("shanson-1", "Радио Шансон", "Радио Шансон", "chanson"),
        _b("shanson-tag-1", "Шансон (авто-подбор #1)", "", "chanson", "chanson"),
        _b("shanson-tag-2", "Шансон (авто-подбор #2)", "", "chanson", "chanson"),
        # Русские радио
        _q("rus-rusradio", "Русское Радио", "Русское Радио", "russian"),
        _q("rus-europa", "Европа Плюс", "Europa Plus", "russian"),
        _q("rus-retro", "Ретро FM", "Retro FM", "russian"),
        _q("rus-record", "Радио Рекорд", "Радио Рекорд", "russian"),
        _q("rus-dfm", "DFM", "DFM", "russian"),
        _b("rus-tag-1", "Русские хиты (авто-подбор)", "", "russian", "russian"),
        # Своё радио: ротация шансона и русских хитов с джинглом каждые 15 минут
        Station(id="trassa-fm", name="Трасса FM", genre="other", builtin=True,
                rotate=["shanson-1", "rus-rusradio", "rus-europa", "rus-retro", "rus-record"],
                rotate_min=15),
        # Рок
        _b("rp-rock", "Radio Paradise — Rock Mix", "https://stream.radioparadise.com/rock-128", "rock"),
        _b("rp-main", "Radio Paradise — Main Mix", "https://stream.radioparadise.com/mp3-128", "rock"),
        _b("soma-u80s", "SomaFM — Underground 80s", "https://ice1.somafm.com/u80s-128-mp3", "retro"),
        # Электроника
        _b("soma-defcon", "SomaFM — DEF CON Radio", "https://ice1.somafm.com/defcon-128-mp3", "electronic"),
        _b("soma-beat", "SomaFM — Beat Blender", "https://ice1.somafm.com/beatblender-128-mp3", "electronic"),
        _b("soma-groove", "SomaFM — Groove Salad", "https://ice1.somafm.com/groovesalad-128-mp3", "electronic"),
        # Phonk — URL подбирается через каталог
        _b("phonk-1", "Phonk (авто-подбор #1)", "", "phonk", "phonk"),
        _b("phonk-2", "Phonk (авто-подбор #2)", "", "phonk", "phonk"),
        # Ретро
        _b("soma-seventies", "SomaFM — Left Coast 70s", "https://ice1.somafm.com/seventies-320-mp3", "retro"),
        _b("retro-1", "Retro (авто-подбор)", "", "retro", "oldies"),
        # Джаз
        _b("soma-sonicuniverse", "SomaFM — Sonic Universe", "https://ice1.somafm.com/sonicuniverse-128-mp3", "jazz"),
        _b("soma-illstreet", "SomaFM — Illinois Street Lounge", "https://ice1.somafm.com/illstreet-128-mp3", "jazz"),
        _b("jazz-1", "Jazz (авто-подбор)", "", "jazz", "jazz"),
        # Новости
        _b("bbc-ws", "BBC World Service", "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service", "news"),
        _b("news-1", "News (авто-подбор)", "", "news", "news"),
    ]


# ---------------------------------------------------------------- radio-browser
def _rb_get(path: str, timeout: float = 6.0):
    """GET к API radio-browser с перебором зеркал. Бросает OSError при полном отказе."""
    last: Exception | None = None
    for base in RB_SERVERS:
        try:
            req = urllib.request.Request(base + path, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:      # noqa: BLE001 — пробуем следующее зеркало
            last = e
    raise OSError(str(last))


def search_online(query: str = "", tag: str = "", limit: int = 30) -> list[dict]:
    """Поиск станций в каталоге. Возвращает [{name, url, tags, codec, bitrate}]."""
    params = {"limit": limit, "hidebroken": "true", "order": "votes", "reverse": "true"}
    if query:
        params["name"] = query
    if tag:
        params["tag"] = tag
    data = _rb_get("/json/stations/search?" + urllib.parse.urlencode(params))
    out = []
    for s in data:
        url = s.get("url_resolved") or s.get("url")
        if url and s.get("lastcheckok", 1):
            out.append({"name": (s.get("name") or "").strip() or url, "url": url,
                        "tags": s.get("tags", ""), "codec": s.get("codec", ""),
                        "bitrate": s.get("bitrate", 0)})
    return out


# ---------------------------------------------------------------- хранилище
class StationStore:
    """Хранит станции в stations.json: встроенные (с избранным) + пользовательские."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (config_dir() / "stations.json")
        self.stations: list[Station] = []
        self.load()

    # ---- загрузка/сохранение ----
    def load(self) -> None:
        saved: dict[str, dict] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for d in json.load(f):
                    saved[d["id"]] = d
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            saved = {}
        result: list[Station] = []
        for st in builtin_stations():
            d = saved.pop(st.id, None)
            if d:                                  # восстановим избранное и найденный URL
                st.favorite = bool(d.get("favorite", False))
                if not st.url and d.get("url"):
                    st.url = d["url"]
            result.append(st)
        for d in saved.values():                   # пользовательские
            try:
                result.append(Station(**{k: v for k, v in d.items()
                                         if k in Station.__dataclass_fields__}))
            except TypeError:
                continue
        self.stations = result

    def save(self) -> None:
        tmp = str(self.path) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([asdict(s) for s in self.stations], f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---- операции ----
    def get(self, sid: str) -> Optional[Station]:
        return next((s for s in self.stations if s.id == sid), None)

    def add(self, name: str, url: str, genre: str = "other") -> Station:
        st = Station(id=uuid.uuid4().hex[:10], name=name.strip() or url, url=url.strip(), genre=genre)
        self.stations.append(st)
        self.save()
        return st

    def add_local(self, files: list[str]) -> Station:
        st = Station(id=uuid.uuid4().hex[:10], name="Local: " + Path(files[0]).name,
                     genre="local", local_files=list(files))
        self.stations.append(st)
        self.save()
        return st

    def remove(self, sid: str) -> bool:
        st = self.get(sid)
        if not st or st.remote:           # станции сервера удаляются только на сервере
            return False
        if st.builtin:
            # Встроенные не удаляем физически (вернулись бы при загрузке) — убираем только избранное.
            st.favorite = False
            self.save()
            return False
        self.stations.remove(st)
        self.save()
        return True

    def merge_remote(self, items: list[dict]) -> int:
        """
        Синхронизирует станции с сервером: добавляет новые, обновляет изменённые,
        убирает пропавшие с сервера. Возвращает число изменений.
        """
        wanted = {"r-" + i["id"]: i for i in items}
        changes = 0
        kept = []
        for s in self.stations:
            if s.remote and s.id not in wanted:
                changes += 1                       # станция удалена на сервере
                continue
            kept.append(s)
        self.stations = kept
        existing = {s.id: s for s in self.stations if s.remote}
        for sid, it in wanted.items():
            st = existing.get(sid)
            if st is None:
                self.stations.append(Station(id=sid, name=it["name"], url=it["url"],
                                             genre=it["genre"], remote=True))
                changes += 1
            elif (st.name, st.url, st.genre) != (it["name"], it["url"], it["genre"]):
                st.name, st.url, st.genre = it["name"], it["url"], it["genre"]
                changes += 1
        if changes:
            self.save()
        return changes

    def toggle_favorite(self, sid: str) -> None:
        st = self.get(sid)
        if st:
            st.favorite = not st.favorite
            self.save()

    def by_genre(self, genre: str) -> list[Station]:
        return [s for s in self.stations if s.genre == genre and s.playable]

    def ensure_url(self, st: Station) -> bool:
        """Для станций с resolve_tag/resolve_query подбирает URL (блокирующий сетевой вызов!)."""
        if st.url or st.is_local or not (st.resolve_tag or st.resolve_query):
            return bool(st.url or st.is_local)
        try:
            if st.resolve_query:
                found = [f for f in search_online(query=st.resolve_query, limit=15)
                         if st.resolve_query.lower() in f["name"].lower()]
            else:
                found = search_online(tag=st.resolve_tag, limit=15)
        except OSError:
            return False
        # Разные авто-станции одного тега получают разные URL.
        used = {s.url for s in self.stations if s.url}
        for f in found:
            if f["url"] not in used:
                st.url = f["url"]
                self.save()
                return True
        if found:
            st.url = found[0]["url"]
            self.save()
            return True
        return False
