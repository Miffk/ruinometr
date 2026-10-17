"""Разбор матча из консоли: py -m ruiner.cli 9046870406"""

import asyncio
import json
import sys

from .config import CACHE_DIR, OPENDOTA_API_KEY, OPENDOTA_MIN_INTERVAL
from .opendota import OpenDota
from .service import AnalysisService, extract_match_id


async def main(argv: list[str]) -> int:
    if not argv:
        print("Использование: py -m ruiner.cli <ID матча или ссылка> [--json] [--refresh]")
        return 2
    match_id = extract_match_id(argv[0])
    od = OpenDota(CACHE_DIR, OPENDOTA_API_KEY, OPENDOTA_MIN_INTERVAL)
    service = AnalysisService(od)
    job = service.get(match_id, refresh="--refresh" in argv)
    last = None
    while job.state not in ("done", "error"):
        if job.message != last:
            print(f"[{int(job.progress * 100):3d}%] {job.message}", file=sys.stderr)
            last = job.message
        await asyncio.sleep(0.5)
    await od.close()
    if job.state == "error":
        print("Ошибка:", job.error, file=sys.stderr)
        return 1
    r = job.result
    if "--json" in argv:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print(f"Матч {r['match_id']}: {r['radiant_score']}:{r['dire_score']}, {r['duration_fmt']}, {r['label']}, "
          f"ранг {r['avg_rank']}, режим: {(r.get('mode') or {}).get('label')} (темп {(r.get('mode') or {}).get('pace')})")
    print(r["summary"])
    for p in r["players"]:
        items = p["items"]
        ref = 'турбо-играм' if items.get('turbo') else 'про-играм'
        item_note = (f"закуп {round(items['score'] * 100)}/100 по {items['samples']} {ref}"
                     if items.get("score") is not None else f"закуп: про-игр {items['samples']}")
        print(f"  {p['team'][:3]} поз.{p['pos']} {p['hero']:<16} {p['kills']}/{p['deaths']}/{p['assists']:<3} "
              f"вклад {p['score']:>3} — {p['verdict_label']} ({p['confidence']}); {item_note}")
    print("Эпизоды:")
    for e in r["episodes"]:
        print(f"  {e['time_fmt']:>6} [{e['severity']}] {e['title']}: {e['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
