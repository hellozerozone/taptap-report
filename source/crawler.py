#!/usr/bin/env python3
"""
TapTap 游戏榜单全量爬虫
========================
覆盖 24 个榜单分类，支持历史游戏持续追踪（掉出榜单的游戏通过批量 API 补抓）。
全量去重后预计 1000-1500 款唯一游戏。

用法:
    python3 crawler.py --all                    # 全量模式 (Android 所有榜单 + 历史追踪)
    python3 crawler.py --all --track            # 全量 + 追踪前一周有但本周掉榜的游戏
    python3 crawler.py --count 100              # 限量模式 (每榜 100 条)
    python3 crawler.py --type hot               # 只爬热门榜

依赖: pip install requests
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

# ── 配置 ──────────────────────────────────────────────────
BASE_URL = "https://www.taptap.cn"
RANKING_API = "/webapiv2/app-top/v2/hits"
MULTI_GET_API = "/webapiv2/app/v1/multi-get-full-platform"
PAGE_SIZE = 15
MULTI_GET_BATCH = 100  # 批量查询每批 ID 数（2026-08 起 API 单批上限 100，超过返回空列表）

# 全部 24 个榜单分类
RANK_TYPES = {
    # 主榜单：150 条/榜
    "hot": "热门榜",
    "reserve": "预约榜",
    "pop": "热玩榜",
    "sell": "热卖榜",
    "exclusive": "独家榜",
    # 100 条级
    "new": "新品榜",
    "in_app_event_reserve": "新版本榜",
    # 品类榜：50 条/榜
    "action": "动作榜",
    "strategy": "策略榜",
    "idle": "放置榜",
    "single": "单机榜",
    "casual": "休闲榜",
    "sandbox_survival": "沙盒生存榜",
    "management": "模拟经营榜",
    "unriddle": "解谜榜",
    "shooter": "射击榜",
    "multiplayer": "多人对战榜",
    "acgn": "二次元榜",
    "music": "音乐节奏榜",
    "scenario": "剧情榜",
    "swordsman": "武侠榜",
    "otome": "女性向榜",
    "independent": "独立游戏榜",
    "roguelike": "Roguelike榜",
}

REQUEST_TIMEOUT = 15
REQUEST_DELAY = 1.2
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8, 15]

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "rankings"


# ── 工具函数 ──────────────────────────────────────────────
def generate_xua() -> str:
    return "&".join(f"{k}={v}" for k, v in {
        "V": "1", "PN": "WebApp", "LANG": "zh_CN", "VN_CODE": "102",
        "LOC": "CN", "PLT": "PC", "DS": "Android",
        "UID": str(uuid.uuid4()), "OS": "MacOS", "OSV": "10.15.7", "DT": "PC",
    }.items())


def build_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.taptap.cn/top/download",
    }


def safe_get(url: str, params: dict, session: requests.Session) -> Optional[dict]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, headers=build_headers(),
                               timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 20
                print(f"    ⚠️ 429 限流，等 {wait}s")
                time.sleep(wait)
            elif resp.status_code == 400:
                return None
            else:
                time.sleep(RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 10)
        except requests.RequestException as e:
            last_error = e
            time.sleep(RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 10)
    return None


# ── 数据提取 ──────────────────────────────────────────────
def extract_game(app_data: dict) -> dict:
    """提取游戏字段。兼容 ranking API（title 是字符串）和 multi-get API（title 是 dict）。"""
    stat = app_data.get("stat", {})
    rating = stat.get("rating", {})

    title = app_data.get("title", "")
    if isinstance(title, dict):
        title = title.get("fallback", title.get("mobile", ""))

    return {
        "id": app_data.get("id"),
        "title": title,
        "score": float(rating.get("score", 0)) if rating.get("score") else None,
        "download_count": stat.get("hits_total", 0),
        "fans_count": stat.get("fans_count", 0),
        "review_count": stat.get("review_count", 0),
        "reserve_count": stat.get("reserve_count", 0),
        "bought_count": stat.get("bought_count", 0),
        "pc_download_count": stat.get("pc_download_count", 0),
        "play_total": stat.get("play_total", 0),
        "feed_count": stat.get("feed_count", 0),
        "topic_count": stat.get("topic_count", 0),
        "video_count": stat.get("video_count", 0),
    }


# ── Phase 1: 榜单爬取 ─────────────────────────────────────
def fetch_one_ranking(
    type_name: str,
    max_total: int,
    session: requests.Session,
) -> list[dict]:
    """分页获取单个榜单的全部游戏。max_total 从 API probe 获取。"""
    games = []
    base_url = f"{BASE_URL}{RANKING_API}"
    page = 0
    next_url = None

    while len(games) < max_total:
        page += 1
        if page == 1:
            url = base_url
            params = {
                "type_name": type_name,
                "limit": PAGE_SIZE,
                "from": 0,
                "X-UA": generate_xua(),
            }
        else:
            if next_url:
                parsed = urlparse(next_url)
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                params["X-UA"] = generate_xua()
                url = base_url
            else:
                break

        data = safe_get(url, params, session)
        if data is None:
            break

        resp_data = data.get("data", {})
        items = resp_data.get("list", [])
        next_url = resp_data.get("next_page", "")

        if not items:
            break

        for item in items:
            if item.get("type") != "app":
                continue
            games.append(extract_game(item.get("app", item)))

        if not next_url or len(games) >= max_total:
            break

        time.sleep(REQUEST_DELAY)

    return games


def crawl_all_rankings(session: requests.Session) -> dict[int, dict]:
    """遍历全部 24 个榜单，去重合并。"""
    all_games: dict[int, dict] = {}
    rankings_stats = {}
    total_fetched = 0

    for type_name, label in RANK_TYPES.items():
        # 先探测 total
        probe = safe_get(
            f"{BASE_URL}{RANKING_API}",
            {"type_name": type_name, "limit": 1, "from": 0, "X-UA": generate_xua()},
            session,
        )
        if probe is None:
            continue

        total = probe.get("data", {}).get("total", 0)
        if total == 0:
            continue

        # 翻页获取
        games = fetch_one_ranking(type_name, total, session)

        new_unique = 0
        for g in games:
            gid = g["id"]
            if gid not in all_games:
                all_games[gid] = g
                new_unique += 1

        rankings_stats[type_name] = {
            "label": label, "total": total, "fetched": len(games),
            "new_unique": new_unique,
        }
        total_fetched += len(games)

        # 进度
        n = len(all_games)
        print(f"  [{label:<8s}] {type_name:<25s} total={total:>3} → "
              f"+{new_unique:>3} unique, 累计 {n:>4} 款")

        time.sleep(REQUEST_DELAY)

    return all_games, rankings_stats, total_fetched


# ── Phase 2: 历史游戏追踪 ─────────────────────────────────
def load_previous_game_ids(exclude_date: str = "") -> set[int]:
    """从最近的快照中加载历史游戏 ID 列表。

    Args:
        exclude_date: 排除的日期目录（重跑当天爬虫时，忽略今天已存在的快照，
                      否则会用今天的部分数据当历史基准）
    """
    if not DATA_DIR.exists():
        return set()

    snapshots = sorted(
        [d for d in DATA_DIR.iterdir() if d.is_dir() and (d / "snapshot.json").exists()],
        key=lambda d: d.name,
        reverse=True,
    )
    if exclude_date:
        snapshots = [d for d in snapshots if d.name != exclude_date]
    if not snapshots:
        return set()

    latest = snapshots[0]
    with open(latest / "snapshot.json", "r") as f:
        snap = json.load(f)
    ids = {g["id"] for g in snap.get("games", [])}
    print(f"\n📦 历史快照: {latest.name} ({len(ids)} 款游戏)")
    return ids


def refresh_missing_games(
    missing_ids: set[int],
    session: requests.Session,
) -> dict[int, dict]:
    """通过 multi-get API 批量获取掉榜游戏的最新数据。"""
    if not missing_ids:
        return {}

    id_list = list(missing_ids)
    refreshed = {}
    batches = (len(id_list) + MULTI_GET_BATCH - 1) // MULTI_GET_BATCH

    print(f"  🔄 补抓 {len(missing_ids)} 款掉榜游戏 ({batches} 批)...")

    for i in range(0, len(id_list), MULTI_GET_BATCH):
        batch = id_list[i : i + MULTI_GET_BATCH]
        ids_str = ",".join(str(x) for x in batch)

        data = safe_get(
            f"{BASE_URL}{MULTI_GET_API}",
            {"ids": ids_str, "X-UA": generate_xua()},
            session,
        )
        if data is None:
            continue

        items = data.get("data", {}).get("list", [])
        for item in items:
            gid = item.get("id")
            if gid:
                refreshed[gid] = extract_game(item)

        batch_num = i // MULTI_GET_BATCH + 1
        print(f"    第 {batch_num}/{batches} 批: {len(items)} 款")

        time.sleep(REQUEST_DELAY)

    return refreshed


# ── 存储 ──────────────────────────────────────────────────
def save_snapshot(games: list[dict], date_str: str, stats: dict):
    date_dir = DATA_DIR / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "date": date_str,
        "fetched_at": datetime.now().isoformat(),
        "stats": stats,
        "games": games,
    }
    filepath = date_dir / "snapshot.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n💾 已保存: {filepath} ({filepath.stat().st_size / 1024:.1f} KB)")


# ── 主入口 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TapTap 游戏全量爬虫（24 榜单 + 历史追踪）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 crawler.py --all                    # 全量模式
  python3 crawler.py --all --track            # 全量 + 追踪掉榜游戏
  python3 crawler.py --count 100              # 限量模式
  python3 crawler.py --type hot               # 只爬热门榜
        """,
    )
    parser.add_argument("--type", "-t", type=str, default=None)
    parser.add_argument("--types", type=str, default=None)
    parser.add_argument("--count", "-c", type=int, default=None)
    parser.add_argument("--all", action="store_true", dest="all_mode")
    parser.add_argument("--track", action="store_true", help="追踪前一周有但本周掉榜的游戏")
    parser.add_argument("--no-track", action="store_true", help="禁用自动追踪")
    parser.add_argument("--delay", "-d", type=float, default=REQUEST_DELAY)
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--list-types", action="store_true")

    args = parser.parse_args()

    if args.list_types:
        for key, label in RANK_TYPES.items():
            print(f"  {key:<25s} - {label}")
        return

    if args.all_mode and args.count:
        print("❌ --all 和 --count 互斥")
        sys.exit(1)

    all_mode = args.all_mode
    count = args.count if args.count else 100
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    # 榜单类型
    if args.types:
        types_to_fetch = [t.strip() for t in args.types.split(",")]
    elif args.type:
        types_to_fetch = [args.type.strip()]
    else:
        types_to_fetch = list(RANK_TYPES.keys())

    for t in types_to_fetch:
        if t not in RANK_TYPES:
            print(f"❌ 未知榜单: {t}")
            sys.exit(1)

    # 历史追踪默认开启 (--all 模式自动)
    track_mode = args.track or (all_mode and not args.no_track)
    if args.count:
        track_mode = False  # 限量模式不追踪

    print("=" * 60)
    print(f"🎮 TapTap 游戏全量爬虫")
    print(f"📅 日期: {date_str}")
    if all_mode:
        print(f"📊 榜单: 全部 {len(RANK_TYPES)} 个")
    else:
        print(f"📊 榜单: {', '.join(types_to_fetch)}")
    print(f"📏 模式: {'全量' if all_mode else '限量'}" + (f" ({count}条/榜)" if not all_mode else ""))
    print(f"🔍 历史追踪: {'开启' if track_mode else '关闭'}")
    print("=" * 60)

    session = requests.Session()

    # ── 限量模式 ──
    if not all_mode:
        total_games = 0
        for type_name in types_to_fetch:
            label = RANK_TYPES[type_name]
            print(f"\n🔍 [{label}] ({type_name})...")
            games = fetch_one_ranking(type_name, count, session)
            print(f"  ✅ {len(games)} 款")

            if games:
                date_dir = DATA_DIR / date_str
                date_dir.mkdir(parents=True, exist_ok=True)
                out = {"date": date_str, "type": type_name, "count": len(games),
                       "fetched_at": datetime.now().isoformat(), "games": games}
                fp = date_dir / f"{type_name}.json"
                json.dump(out, open(fp, "w"), ensure_ascii=False, indent=2)
                total_games += len(games)

            time.sleep(args.delay)
        print(f"\n📋 总计: {total_games} 条")
        return

    # ── 全量模式 ──
    # Phase 1: 爬取全部 24 个榜单
    print(f"\n📊 Phase 1: 榜单全量爬取 ({len(types_to_fetch)} 个榜单)")
    print("-" * 40)
    all_games, rankings_stats, total_fetched = crawl_all_rankings(session)

    # Phase 2: 历史追踪（如果开启）
    tracked_count = 0
    if track_mode:
        print(f"\n📊 Phase 2: 历史游戏追踪")
        print("-" * 40)
        prev_ids = load_previous_game_ids(exclude_date=date_str)
        if prev_ids:
            missing = prev_ids - set(all_games.keys())
            if missing:
                refreshed = refresh_missing_games(missing, session)
                for gid, g in refreshed.items():
                    if gid not in all_games:
                        all_games[gid] = g
                        tracked_count += 1
                print(f"  ✅ 追回 {tracked_count} 款（掉榜但持续跟踪）")
            else:
                print(f"  ✅ 无掉榜游戏，全部 {len(prev_ids)} 款均在榜单内")
        else:
            print(f"  📌 无历史快照，跳过追踪")

    # 排序
    sorted_games = sorted(all_games.values(), key=lambda g: g["download_count"], reverse=True)
    for i, g in enumerate(sorted_games):
        g["rank"] = i + 1

    # 汇总统计
    stats = {
        "mode": "all_24_rankings",
        "rankings": rankings_stats,
        "total_fetched": total_fetched,
        "unique_from_rankings": len(all_games) - tracked_count,
        "tracked_from_history": tracked_count,
        "final_unique": len(sorted_games),
    }

    save_snapshot(sorted_games, date_str, stats)

    # 摘要
    print(f"\n📋 最终统计:")
    print(f"  榜单获取: {total_fetched} 条 → 去重 {stats['unique_from_rankings']} 款")
    if tracked_count:
        print(f"  历史追踪: +{tracked_count} 款")
    print(f"  最终总数: {stats['final_unique']} 款唯一游戏")

    # Top 10
    print(f"\n🏆 下载量 TOP 10:")
    for g in sorted_games[:10]:
        dl = g["download_count"]
        dl_s = f"{dl/10000:.0f}万" if dl >= 10000 else str(dl)
        print(f"  #{g['rank']:>4} {g['title']:<25s} {dl_s:>8s}  评分:{g['score']}")

    # 零下载游戏
    zero = sum(1 for g in sorted_games if g["download_count"] == 0)
    if zero:
        print(f"\n  📌 {zero} 款游戏下载量为 0（预约/未发布）")

    print("=" * 60)


if __name__ == "__main__":
    main()
