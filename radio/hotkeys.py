"""
Глобальные горячие клавиши (работают, пока окно игры в фокусе).

Используется pynput.keyboard.GlobalHotKeys — на Windows это низкоуровневый
хук без прав администратора. Колбэки вызываются из потока pynput, поэтому
наружу отдаём имя действия через переданную функцию (в UI она превращается
в Qt-сигнал и безопасно переносится в главный поток).

Примечание: если BeamNG запущена «от администратора», Windows может не
пропускать хуки из обычного процесса — запускайте радио так же.
"""
from __future__ import annotations

from typing import Callable, Optional


def validate_hotkey(combo: str) -> bool:
    """Проверяет строку вида '<ctrl>+<alt>+p' без регистрации."""
    try:
        from pynput import keyboard
        keyboard.HotKey.parse(combo)
        return True
    except Exception:                       # noqa: BLE001
        return False


class HotkeyManager:
    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        self._listener = None
        self.error: Optional[str] = None

    def apply(self, mapping: dict[str, str]) -> list[str]:
        """
        Перерегистрирует все хоткеи. mapping: {action: combo}.
        Возвращает список действий с некорректной комбинацией.
        """
        self.stop()
        try:
            from pynput import keyboard
        except Exception as e:              # noqa: BLE001
            self.error = str(e)
            return list(mapping)
        bad: list[str] = []
        table = {}
        for action, combo in mapping.items():
            if not combo or not validate_hotkey(combo):
                bad.append(action)
                continue
            table[combo] = (lambda a=action: self.emit(a))
        if table:
            try:
                self._listener = keyboard.GlobalHotKeys(table)
                self._listener.daemon = True
                self._listener.start()
            except Exception as e:          # noqa: BLE001
                self.error = str(e)
        return bad

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:               # noqa: BLE001
                pass
            self._listener = None
