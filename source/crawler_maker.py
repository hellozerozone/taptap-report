#!/usr/bin/env python3
"""
TapTap Maker（制造）游戏爬虫
============================
专门爬取 TapTap Maker 平台的游戏数据，与主站爬虫独立运行。
Maker 是 TapTap 的游戏创作平台（用户自制游戏），目前约 115 款。
数据保存到 data/tapmaker_rankings/ 目录。

用法:
    python3 crawler_maker.py                    # 全量爬取所有 Maker 游戏
    python3 crawler_maker.py --count 30         # 限量模式（前 30 款）

依赖: pip install requests

注意: 本脚本仅供个人学习研究使用。
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
API_PATH = "/webapiv2/maker/v1/app-list"

# Maker 游戏总数约 5000 款，单页上限 56
# 注意: 2026-08 API 变更后，首页 (from=0) 的 limit 过大(如 56)会返回空列表，需用 20
PAGE_SIZE = 56
FIRST_PAGE_SIZE = 20

REQUEST_TIMEOUT = 15
REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8, 15]

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "tapmaker_rankings"


# ── 工具函数 ──────────────────────────────────────────────
def generate_xua() -> str:
    params = {
        "V": "1",
        "PN": "WebApp",
        "LANG": "zh_CN",
        "VN_CODE": "102",
        "LOC": "CN",
        "PLT": "PC",
        "DS": "Android",
        "UID": str(uuid.uuid4()),
        "OS": "MacOS",
        "OSV": "10.15.7",
        "DT": "PC",
    }
    return "&".join(f"{k}={v}" for k, v in params.items())


def build_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.taptap.cn/maker",
    }


def safe_get(url: str, params: dict, session: requests.Session) -> Optional[dict]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(
                url, params=params, headers=build_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 20
                print(f"  ⚠️ 429 限流，等待 {wait}s ...")
                time.sleep(wait)
            elif resp.status_code == 400:
                print(f"  ❌ HTTP 400 参数错误: {resp.text[:100]}")
                return None
            else:
                print(f"  ⚠️ HTTP {resp.status_code}，重试 {attempt+1}/{MAX_RETRIES}")
                time.sleep(RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 10)
        except requests.RequestException as e:
            last_error = e
            wait = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 10
            print(f"  ⚠️ 请求异常: {e}，等待 {wait}s ...")
            time.sleep(wait)

    print(f"  ❌ 请求最终失败: {last_error}")
    return None


# ── 数据提取 ──────────────────────────────────────────────
def extract_game(app_data: dict) -> dict:
    """
    从 Maker API 返回的游戏对象提取字段。
    字段结构与主站 API 一致，hits_total = 累计下载量。
    """
    stat = app_data.get("stat", {})
    rating = stat.get("rating", {})
    return {
        "id": app_data.get("id"),
        "title": app_data.get("title", ""),
        "identifier": app_data.get("identifier", ""),
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


# ── 爬取逻辑 ──────────────────────────────────────────────
def fetch_all_maker_games(
    max_count: int,
    session: requests.Session,
) -> list[dict]:
    """
    分页获取所有 Maker 游戏。

    Args:
        max_count: 最多获取多少条（用于限量模式）
        session: requests.Session
    """
    base_url = f"{BASE_URL}{API_PATH}"
    all_games: dict[int, dict] = {}  # id -> game
    page = 0
    next_url = None
    total_hint = 0

    while len(all_games) < max_count:
        page += 1

        if page == 1:
            url = base_url
            # 2026-08 API 变更: 必须带空的 ids 参数 + 数字 sort；
            # 首页 limit 用 FIRST_PAGE_SIZE，后续页可从 next_page 加大到 PAGE_SIZE
            params = {
                "ids": "",
                "from": 0,
                "limit": min(FIRST_PAGE_SIZE, max_count),
                "sort": 1,
                "X-UA": generate_xua(),
            }
        else:
            if next_url:
                parsed = urlparse(next_url)
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                params["limit"] = min(PAGE_SIZE, max_count)
                params["X-UA"] = generate_xua()
                url = base_url
            else:
                break

        print(f"  📄 第 {page} 页...", end=" ")

        data = safe_get(url, params, session)
        if data is None:
            break

        resp_data = data.get("data", {})
        items = resp_data.get("list", [])
        next_url = resp_data.get("next_page", "")

        if not items:
            print("无更多数据")
            break

        new_count = 0
        for item in items:
            gid = item.get("id")
            if gid in all_games:
                continue
            game = extract_game(item)
            all_games[gid] = game
            new_count += 1
            if len(all_games) >= max_count:
                break

        print(f"获取 {new_count} 条 (累计 {len(all_games)})")
        total_hint = max(total_hint, len(all_games) + int(bool(next_url)) * PAGE_SIZE)

        if len(all_games) >= max_count or not next_url:
            break

        time.sleep(REQUEST_DELAY)

    # 转为列表并按下载量降序
    games = sorted(all_games.values(), key=lambda g: g["download_count"], reverse=True)
    for i, g in enumerate(games):
        g["rank"] = i + 1

    return games


# ── 存储 ──────────────────────────────────────────────────
def save_snapshot(games: list[dict], date_str: str):
    date_dir = DATA_DIR / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "date": date_str,
        "platform": "tapmaker",
        "fetched_at": datetime.now().isoformat(),
        "total_games": len(games),
        "games": games,
    }

    filepath = date_dir / "snapshot.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    size_kb = filepath.stat().st_size / 1024
    print(f"\n  💾 已保存: {filepath} ({size_kb:.1f} KB)")
    return filepath


# ── 主入口 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TapTap Maker 游戏爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 crawler_maker.py               # 全量模式（所有 Maker 游戏）
  python3 crawler_maker.py --count 30    # 限量模式（前 30 款）
        """,
    )
    parser.add_argument("--count", "-c", type=int, default=0, help="获取条数 (默认 0 = 全量)")
    parser.add_argument("--delay", "-d", type=float, default=REQUEST_DELAY, help="请求间隔秒数")
    parser.add_argument("--date", type=str, default=None, help="日期标识 (默认今天)")

    args = parser.parse_args()

    # 全量模式：设置一个较大的值，实际会爬到 API 无更多数据为止
    max_count = args.count if args.count > 0 else 9999
    mode = "限量" if args.count > 0 else "全量"
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"🎮 TapTap Maker 游戏爬虫")
    print(f"📅 日期: {date_str}")
    print(f"📏 模式: {mode}" + (f" ({max_count} 条)" if args.count > 0 else ""))
    print(f"📁 数据目录: {DATA_DIR}")
    print("=" * 60)

    session = requests.Session()

    print(f"\n🔍 正在爬取 TapTap Maker 游戏列表...")
    try:
        games = fetch_all_maker_games(max_count=max_count, session=session)
        print(f"  ✅ 完成: 共获取 {len(games)} 款 Maker 游戏")

        if games:
            save_snapshot(games, date_str)

            # 摘要
            print(f"\n📋 Maker 游戏摘要:")
            print(f"  总数: {len(games)} 款")
            total_dl = sum(g["download_count"] for g in games)
            print(f"  总下载量: {total_dl:,}")
            print(f"\n  🏆 下载量 TOP 10:")
            for g in games[:10]:
                dl = g["download_count"]
                dl_str = f"{dl/10000:.1f}万" if dl >= 10000 else str(dl)
                print(f"  #{g['rank']:>3} {g['title']:<25s} {dl_str:>10s}  "
                      f"评分:{g['score']}  关注:{g['fans_count']:,}")
        else:
            print("  ⚠️ 未获取到数据")

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断")
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        import traceback
        traceback.print_exc()

    print("=" * 60)


if __name__ == "__main__":
    main()
