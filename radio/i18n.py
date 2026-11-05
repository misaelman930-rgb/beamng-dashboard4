"""Простейшая локализация RU/EN. tr('key') возвращает строку текущего языка."""
from __future__ import annotations

_LANG = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "app_title": {"ru": "BeamNG Radio", "en": "BeamNG Radio"},
    "connected": {"ru": "Подключено к BeamNG", "en": "Connected to BeamNG"},
    "waiting": {"ru": "Ожидание игры…", "en": "Waiting for game…"},
    "port_error": {"ru": "Порт занят / недоступен", "en": "Port busy / unavailable"},
    "stations": {"ru": "Станции", "en": "Stations"},
    "favorites": {"ru": "★ Избранное", "en": "★ Favorites"},
    "all": {"ru": "Все", "en": "All"},
    "add_station": {"ru": "Добавить станцию", "en": "Add station"},
    "remove_station": {"ru": "Удалить", "en": "Remove"},
    "add_local": {"ru": "Локальные файлы…", "en": "Local files…"},
    "find_online": {"ru": "Найти онлайн…", "en": "Find online…"},
    "name": {"ru": "Название", "en": "Name"},
    "url": {"ru": "URL потока", "en": "Stream URL"},
    "genre": {"ru": "Жанр", "en": "Genre"},
    "play": {"ru": "Играть", "en": "Play"},
    "pause": {"ru": "Пауза", "en": "Pause"},
    "next": {"ru": "Следующая", "en": "Next"},
    "prev": {"ru": "Предыдущая", "en": "Previous"},
    "mute": {"ru": "Без звука", "en": "Mute"},
    "volume": {"ru": "Громкость", "en": "Volume"},
    "no_track": {"ru": "—", "en": "—"},
    "buffering": {"ru": "Буферизация…", "en": "Buffering…"},
    "stream_error": {"ru": "Поток недоступен, пробую снова…", "en": "Stream unavailable, retrying…"},
    "skip_dead": {"ru": "Станция не отвечает, следующая", "en": "Station not responding, skipping"},
    "settings": {"ru": "Настройки", "en": "Settings"},
    "general": {"ru": "Общие", "en": "General"},
    "remote_server": {"ru": "Сервер станций (URL)", "en": "Stations server (URL)"},
    "remote_error": {"ru": "Сервер станций недоступен, использую сохранённый список",
                     "en": "Stations server unreachable, using saved list"},
    "remote_bad_url": {"ru": "Некорректный URL сервера станций", "en": "Invalid stations server URL"},
    "effects": {"ru": "Эффекты", "en": "Effects"},
    "rules": {"ru": "Правила", "en": "Rules"},
    "overlay": {"ru": "Оверлей", "en": "Overlay"},
    "click_through": {"ru": "Click-through", "en": "Click-through"},
    "language": {"ru": "Язык", "en": "Language"},
    "udp_port": {"ru": "UDP-порт OutGauge", "en": "OutGauge UDP port"},
    "audio_device": {"ru": "Аудиоустройство", "en": "Audio device"},
    "default_device": {"ru": "По умолчанию (система)", "en": "System default"},
    "refresh": {"ru": "Обновить", "en": "Refresh"},
    "speed_volume": {"ru": "Громкость от скорости", "en": "Speed-based volume"},
    "curve": {"ru": "Кривая (км/ч → %)", "en": "Curve (km/h → %)"},
    "add_point": {"ru": "+ точка", "en": "+ point"},
    "del_point": {"ru": "− точка", "en": "− point"},
    "car_filter": {"ru": "Эффект «радио в машине»", "en": "“Car radio” effect"},
    "strength": {"ru": "Сила", "en": "Strength"},
    "rpm_max": {"ru": "Обороты макс. эффекта", "en": "RPM for max effect"},
    "auto_genre": {"ru": "Автосмена жанра", "en": "Auto genre switch"},
    "calm_genre": {"ru": "Спокойный жанр", "en": "Calm genre"},
    "energetic_genre": {"ru": "Энергичный жанр", "en": "Energetic genre"},
    "calm_below": {"ru": "Спокойный ниже (км/ч)", "en": "Calm below (km/h)"},
    "energetic_above": {"ru": "Энергичный выше (км/ч)", "en": "Energetic above (km/h)"},
    "min_interval": {"ru": "Мин. интервал (с)", "en": "Min interval (s)"},
    "hotkeys": {"ru": "Горячие клавиши", "en": "Hotkeys"},
    "hotkey_hint": {"ru": "Формат: <ctrl>+<alt>+p", "en": "Format: <ctrl>+<alt>+p"},
    "enabled": {"ru": "Включено", "en": "Enabled"},
    "rule_name": {"ru": "Название", "en": "Name"},
    "variable": {"ru": "Переменная", "en": "Variable"},
    "operator": {"ru": "Оператор", "en": "Operator"},
    "value": {"ru": "Значение", "en": "Value"},
    "for_s": {"ru": "Держится, с", "en": "Held for, s"},
    "action": {"ru": "Действие", "en": "Action"},
    "param": {"ru": "Параметр", "en": "Parameter"},
    "mode": {"ru": "Режим", "en": "Mode"},
    "cooldown": {"ru": "Пауза, с", "en": "Cooldown, s"},
    "add_rule": {"ru": "Добавить правило", "en": "Add rule"},
    "del_rule": {"ru": "Удалить правило", "en": "Delete rule"},
    "save": {"ru": "Сохранить", "en": "Save"},
    "cancel": {"ru": "Отмена", "en": "Cancel"},
    "close": {"ru": "Закрыть", "en": "Close"},
    "search": {"ru": "Поиск", "en": "Search"},
    "search_hint": {"ru": "Название или тег (например: phonk)", "en": "Name or tag (e.g. phonk)"},
    "network_error": {"ru": "Ошибка сети", "en": "Network error"},
    "rules_hint": {
        "ru": "Если [переменная] [оператор] [значение] (держится N с) → [действие]. "
              "Режим while — пока условие истинно; once — один раз по фронту.",
        "en": "If [variable] [op] [value] (held N s) → [action]. "
              "Mode while = while true; once = once on rising edge."},
    "tray_show": {"ru": "Показать", "en": "Show"},
    "tray_quit": {"ru": "Выход", "en": "Quit"},
    "local_files": {"ru": "Локальные файлы", "en": "Local files"},
    "device_changed": {"ru": "Аудиоустройство изменилось, перезапуск потока",
                       "en": "Audio device changed, restarting stream"},
    "vlc_missing": {"ru": "Не найден VLC. Установите VLC (64-бит) с videolan.org.",
                    "en": "VLC not found. Install VLC (64-bit) from videolan.org."},
    "now_rules": {"ru": "Активные правила", "en": "Active rules"},
    "gear": {"ru": "Передача", "en": "Gear"},
    "speed": {"ru": "Скорость", "en": "Speed"},
    "rpm": {"ru": "Обороты", "en": "RPM"},
    "fuel": {"ru": "Топливо", "en": "Fuel"},
    "temp": {"ru": "Темп.", "en": "Temp"},
    "launch_beamng": {"ru": "Запустить BeamNG", "en": "Launch BeamNG"},
    "beamng_path": {"ru": "Путь к BeamNG.drive.exe", "en": "Path to BeamNG.drive.exe"},
}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in ("ru", "en") else "ru"


def get_language() -> str:
    return _LANG


def tr(key: str) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(_LANG) or entry.get("en") or key
