"""Профиль режима игры: в турбо всё быстрее, поэтому окна времени, суммы золота и пороги другие.

build_report выставляет профиль на время сборки отчёта (сборка синхронная, один отчёт за раз),
модули читают значения через mode.P.
"""

from dataclasses import dataclass

TURBO_GAME_MODE = 23
GAME_MODES = {1: "All Pick", 2: "Captains Mode", 3: "Random Draft", 4: "Single Draft", 5: "All Random",
              12: "Least Played", 16: "Captains Draft", 18: "Ability Draft", 22: "Ranked All Pick", 23: "Турбо"}


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    pace: float              # во сколько раз быстрее копится золото: 1.0 — обычная игра, ~0.55 — турбо
    lane_minute: int         # до какой минуты считаем линию
    final_window: int        # «финал» — последние N секунд
    pocket_gold: int         # с какой суммы смерть — «деньги в кармане»
    buyback_reserve_from: int
    comeback_gold: int
    stomp_gold: int
    confident_gold: int

    @property
    def lane_end(self) -> int:
        return self.lane_minute * 60

    @property
    def is_turbo(self) -> bool:
        return self.key == "turbo"

    def t(self, seconds: float) -> float:
        """Масштабировать длительность обычной игры на темп режима."""
        return seconds * self.pace


NORMAL = Profile("normal", "Обычная игра", 1.0, 10, 300, 2000, 20 * 60, 8000, 25000, 10000)


def turbo(pace: float) -> Profile:
    pace = max(0.35, min(0.9, pace))
    return Profile(
        key="turbo", label="Турбо", pace=pace,
        lane_minute=max(5, min(8, round(10 * pace))),
        final_window=180,
        pocket_gold=int(round(2000 / pace, -2)),
        buyback_reserve_from=int(20 * 60 * pace),
        comeback_gold=int(8000 / pace), stomp_gold=int(25000 / pace), confident_gold=int(10000 / pace),
    )


P: Profile = NORMAL


def use(profile: Profile) -> None:
    global P
    P = profile


def is_turbo_match(match: dict) -> bool:
    return match.get("game_mode") == TURBO_GAME_MODE
