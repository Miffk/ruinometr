"""Чистка кэша: на сервере с маленьким диском data/ не должна расти бесконечно."""

import time
from pathlib import Path

# Справочники героев и предметов нужны всегда — их не трогаем (они и так обновляются по TTL).
KEEP_PREFIXES = ("const_",)


def _files(data_dir: Path) -> list[Path]:
    return [p for p in data_dir.rglob("*") if p.is_file() and not p.name.startswith(KEEP_PREFIXES)]


def cleanup(data_dir: Path, max_age_days: float, max_mb: float) -> dict:
    """Удалить файлы старше max_age_days, затем самые старые — пока data/ не станет меньше max_mb."""
    if not data_dir.exists():
        return {"removed": 0, "freed_mb": 0.0}
    now = time.time()
    removed, freed = 0, 0
    files = []
    for p in _files(data_dir):
        try:
            st = p.stat()
        except OSError:
            continue
        if now - st.st_mtime > max_age_days * 86400:
            try:
                p.unlink()
                removed += 1
                freed += st.st_size
            except OSError:
                pass
        else:
            files.append((st.st_mtime, st.st_size, p))
    total = sum(size for _, size, _ in files)
    limit = max_mb * 1024 * 1024
    for _, size, p in sorted(files):
        if total <= limit:
            break
        try:
            p.unlink()
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass
    return {"removed": removed, "freed_mb": round(freed / 1024 / 1024, 1)}
