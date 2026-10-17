"""Справочники героев и предметов из OpenDota."""

import re

CDN = "https://cdn.cloudflare.steamstatic.com"

# Предметы, которые считаем ключевыми независимо от цены и того, во что они собираются дальше.
EXTRA_KEY_ITEMS = {"blink", "aghanims_shard", "tranquil_boots", "arcane_boots", "phase_boots", "power_treads",
                   "travel_boots", "travel_boots_2", "guardian_greaves", "boots_of_bearing"}
# Промежуточные предметы дешевле этого порога (Oblivion Staff, Vanguard…) не считаем целью закупа;
# дороже (Dragon Lance, Yasha, Kaya) — считаем: это заметный шаг сборки.
INTERMEDIATE_MIN_COST = 1800

RANK_NAMES = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"]


def _ability_name(key: str, dname: str | None) -> str:
    """Название способности или таланта. В талантах OpenDota оставляет шаблоны вроде «+{s:bonus_radius}» — убираем."""
    if dname:
        name = re.sub(r"[+\-]?\{s:[^}]*\}[%s]?\s*", "", dname).strip()
        if name:
            return name
    hero_part = re.sub(r"^special_bonus_(unique_)?", "", key)
    return "Талант: " + hero_part.replace("_", " ") if key.startswith("special_bonus") else key


def _img(path: str | None) -> str | None:
    if not path:
        return None
    return CDN + path.split("?")[0]


class Constants:
    def __init__(self, heroes: dict, items: dict, chat_wheel: dict, ability_ids: dict | None = None,
                 abilities: dict | None = None, hero_abilities: dict | None = None):
        # В справочнике встречаются составные ключи вида "3060,1617" — они нам не нужны.
        self.ability_ids = {int(k): v for k, v in (ability_ids or {}).items() if k.isdigit()}
        self.abilities = abilities or {}
        self.hero_abilities = hero_abilities or {}
        self.heroes = {int(k): v for k, v in heroes.items()}
        self.heroes_by_npc = {h["name"]: h for h in self.heroes.values()}
        self.items = items
        self.item_key_by_id = {it.get("id"): key for key, it in items.items() if not key.startswith("recipe_")}
        self.chat_wheel = chat_wheel
        self._key_items = self._compute_key_items()

    def _compute_key_items(self) -> set[str]:
        component_of_something = set()
        for it in self.items.values():
            for c in it.get("components") or []:
                component_of_something.add(c)
        keys = set()
        for key, it in self.items.items():
            if key.startswith("recipe_"):
                continue
            cost = it.get("cost") or 0
            is_key = key in EXTRA_KEY_ITEMS or (it.get("created") and cost >= 1000)
            if not is_key:
                continue
            # Дешёвые промежуточные компоненты без активки — не цель закупа.
            has_active = any(a.get("type") in ("active", "toggle") for a in it.get("abilities") or [])
            if (key in component_of_something and not has_active and key not in EXTRA_KEY_ITEMS
                    and cost < INTERMEDIATE_MIN_COST):
                continue
            keys.add(key)
        return keys

    # --- герои ---

    def hero_name(self, hero_id: int) -> str:
        h = self.heroes.get(hero_id)
        return h["localized_name"] if h else f"Hero {hero_id}"

    def hero_img(self, hero_id: int) -> str | None:
        h = self.heroes.get(hero_id)
        return _img(h.get("img")) if h else None

    def hero_name_by_npc(self, npc: str) -> str:
        h = self.heroes_by_npc.get(npc)
        if h:
            return h["localized_name"]
        return npc.replace("npc_dota_hero_", "").replace("_", " ").title()

    # --- предметы ---

    def item_name(self, key: str) -> str:
        it = self.items.get(key)
        return it.get("dname") or key if it else key

    def item_img(self, key: str) -> str | None:
        it = self.items.get(key)
        return _img(it.get("img")) if it else None

    def item_cost(self, key: str) -> int:
        it = self.items.get(key)
        return (it.get("cost") or 0) if it else 0

    def is_key_item(self, key: str) -> bool:
        return key in self._key_items

    def item_ref(self, key: str) -> dict:
        return {"key": key, "name": self.item_name(key), "img": self.item_img(key)}

    # --- способности ---

    def ability_key(self, ability_id: int) -> str | None:
        return self.ability_ids.get(int(ability_id))

    def ability_ref(self, key: str) -> dict:
        a = self.abilities.get(key) or {}
        return {"key": key, "name": _ability_name(key, a.get("dname")), "img": _img(a.get("img"))}

    def hero_talents(self, hero_id: int) -> dict[str, int]:
        """Таланты героя → ярус 1..4 (10, 15, 20, 25 уровень)."""
        npc = self.heroes.get(hero_id, {}).get("name", "")
        return {t["name"]: t["level"] for t in (self.hero_abilities.get(npc) or {}).get("talents") or []}

    def is_ultimate(self, key: str) -> bool:
        """Ульт — способность с тремя уровнями (по длине списка перезарядок или маны)."""
        a = self.abilities.get(key) or {}
        for field in ("cd", "mc"):
            v = a.get(field)
            if isinstance(v, list) and v:
                return len(v) == 3
        return False

    # --- прочее ---

    def chat_wheel_text(self, key: str) -> str:
        entry = self.chat_wheel.get(str(key))
        if not entry:
            return "фраза из колеса"
        return entry.get("message") or entry.get("label") or entry.get("name") or "фраза из колеса"


def rank_name(rank_tier: float | None) -> str | None:
    if not rank_tier:
        return None
    tier = int(round(rank_tier))
    medal, stars = divmod(tier, 10)
    if not 1 <= medal <= len(RANK_NAMES):
        return None
    name = RANK_NAMES[medal - 1]
    return f"{name} {stars}" if stars and medal < 8 else name


async def load_constants(od) -> Constants:
    heroes = await od.constants("heroes")
    items = await od.constants("items")
    chat_wheel = await od.constants("chat_wheel")
    ability_ids = await od.constants("ability_ids")
    abilities = await od.constants("abilities")
    hero_abilities = await od.constants("hero_abilities")
    return Constants(heroes, items, chat_wheel, ability_ids, abilities, hero_abilities)
