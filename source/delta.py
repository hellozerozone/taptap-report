#!/usr/bin/env python3
"""
TapTap 周新增数据计算脚本
=========================
加载两周的快照数据，按游戏 ID 匹配，计算本周各项指标的增量。
按周新增下载量降序排列，输出 JSON 和 CSV 文件。

用法:
    python3 delta.py                                    # 自动匹配最近两周
    python3 delta.py --this 2026-08-16 --last 2026-08-09  # 手动指定
    python3 delta.py --top 600                          # 只保留前 600 名
    python3 delta.py --all-weeks                        # 对全部周批量计算

依赖: 无需额外安装（仅用标准库）
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 配置 ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
RANKINGS_DIR = ROOT / "data" / "rankings"
DELTAS_DIR = ROOT / "data" / "deltas"

# 需要计算增量的累计指标（本周 - 上周）
CUMULATIVE_FIELDS = [
    "download_count",
    "fans_count",
    "review_count",
    "reserve_count",
    "bought_count",
    "pc_download_count",
    "play_total",
    "feed_count",
    "topic_count",
    "video_count",
]

# 累计字段 → 增量字段名 的映射
DELTA_FIELD_MAP = {
    "download_count": "new_downloads",
    "fans_count": "new_fans",
    "review_count": "new_reviews",
    "reserve_count": "new_reserves",
    "bought_count": "new_bought",
    "pc_download_count": "new_pc_downloads",
    "play_total": "new_plays",
    "feed_count": "new_feeds",
    "topic_count": "new_topics",
    "video_count": "new_videos",
}

# 不需要计算增量的字段（直接继承本周值）
PASSTHROUGH_FIELDS = [
    "id",
    "title",
    "score",
    "rank",
]


# ── 广告嫌疑评分 ──────────────────────────────────────────
def compute_ad_signals(g: dict) -> dict:
    """
    根据周增量数据计算广告嫌疑信号。

    评分维度：
      1. 评论率异常：下载暴增但几乎无人评论（权重 40）
      2. 关注率异常：下载了但不点关注（权重 30）
      3. 增长率异常：环比突然暴涨（权重 30）
      4. 零评论：有下载但完全无人评论（加分 20）

    Returns:
        dict with review_rate, follow_rate, growth_rate, ad_score (0-100)
    """
    new_dl = max(g.get("new_downloads", 0), 0)
    new_reviews = max(g.get("new_reviews", 0), 0)
    new_fans = max(g.get("new_fans", 0), 0)
    prev_dl = max(g.get("prev_download_count", 0), 0)

    score = 0
    signals = {}

    # ── Signal 1: 评论率 (每万下载的评论数) ──
    if new_dl >= 1000:
        review_rate = (new_reviews / new_dl) * 10000
        signals["review_rate_per_10k_dl"] = round(review_rate, 1)

        if review_rate < 3:
            score += 40
            signals["review_flag"] = "🔴 极低评论率"
        elif review_rate < 10:
            score += 25
            signals["review_flag"] = "🟡 偏低评论率"
        elif review_rate < 30:
            score += 5
            signals["review_flag"] = "🟢 正常"
        else:
            score -= 10
            signals["review_flag"] = "✅ 高互动"
    else:
        signals["review_rate_per_10k_dl"] = None
        signals["review_flag"] = "⏭ 下载量太小不评估"

    # ── Signal 2: 关注转化率 ──
    if new_dl >= 1000:
        follow_rate = (new_fans / new_dl) * 100
        signals["follow_rate_pct"] = round(follow_rate, 1)

        if follow_rate < 5:
            score += 30
            signals["follow_flag"] = "🔴 极低关注转化"
        elif follow_rate < 15:
            score += 15
            signals["follow_flag"] = "🟡 偏低关注转化"
        elif follow_rate < 40:
            score += 0
            signals["follow_flag"] = "🟢 正常"
        else:
            score -= 10
            signals["follow_flag"] = "✅ 高关注转化"
    else:
        signals["follow_rate_pct"] = None
        signals["follow_flag"] = "⏭ 下载量太小不评估"

    # ── Signal 3: 增长率异常 ──
    if prev_dl >= 10000:
        growth_rate = (new_dl / prev_dl) * 100
        signals["growth_rate_pct"] = round(growth_rate, 1)

        if growth_rate > 200:
            score += 30
            signals["growth_flag"] = "🔴 环比暴涨"
        elif growth_rate > 80:
            score += 15
            signals["growth_flag"] = "🟡 环比偏高"
        else:
            signals["growth_flag"] = "🟢 正常增长"
    else:
        # 新游戏，累计量小，增长率无意义
        signals["growth_rate_pct"] = None
        if new_dl > 50000:
            score += 10  # 新游戏突然有大额下载，轻度可疑
            signals["growth_flag"] = "🆕 新游大量下载"
        else:
            signals["growth_flag"] = "🆕 新游戏"

    # ── Signal 4: 零评论惩罚 ──
    if new_dl >= 5000 and new_reviews == 0:
        score += 20
        signals["zero_review_flag"] = "⚠️ 有下载但零评论"

    # 归一化到 0-100
    signals["ad_score"] = max(0, min(100, score))

    # 定性标签
    if signals["ad_score"] >= 70:
        signals["ad_level"] = "🔴 高概率广告导入"
    elif signals["ad_score"] >= 40:
        signals["ad_level"] = "🟡 可能有广告"
    elif signals["ad_score"] >= 15:
        signals["ad_level"] = "🟢 自然增长为主"
    else:
        signals["ad_level"] = "✅ 自然增长"

    return signals


# ── 工具函数 ──────────────────────────────────────────────
def load_snapshot(date_str: str) -> Optional[dict]:
    """加载指定日期的快照文件"""
    filepath = RANKINGS_DIR / date_str / "snapshot.json"
    if not filepath.exists():
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def find_available_weeks() -> list[str]:
    """列出所有有快照数据的周日期，按日期升序"""
    if not RANKINGS_DIR.exists():
        return []
    weeks = []
    for d in sorted(RANKINGS_DIR.iterdir()):
        if d.is_dir() and (d / "snapshot.json").exists():
            weeks.append(d.name)
    return sorted(weeks)


# ── 核心计算 ──────────────────────────────────────────────
def compute_delta(
    this_snapshot: dict,
    last_snapshot: dict,
    top_n: Optional[int] = None,
) -> dict:
    """
    计算两周之间的增量。

    Args:
        this_snapshot: 本周快照
        last_snapshot: 上周快照
        top_n: 只保留前 N 名（按 new_downloads 排序），None 表示全部保留

    Returns:
        delta 结果 dict
    """
    # 建立上周索引 {id: game}
    last_index: dict[int, dict] = {}
    for g in last_snapshot.get("games", []):
        last_index[g["id"]] = g

    this_games = this_snapshot.get("games", [])
    delta_games = []
    new_to_pool_count = 0  # 首次进入游戏池（无历史数据）
    first_day_games = []   # 首日下载游戏（昨日累计=0）

    for g in this_games:
        gid = g["id"]
        prev = last_index.get(gid)

        delta_game = {}
        # 直接继承本周的非累计字段
        for field in PASSTHROUGH_FIELDS:
            delta_game[field] = g.get(field)

        # 判断游戏状态
        is_new_to_pool = (prev is None)  # 首次进入游戏池，无历史数据
        is_first_day = (not is_new_to_pool and prev.get("download_count", 0) == 0)  # 昨日累计=0，今天是首日有下载

        # 计算累计字段的增量
        for field in CUMULATIVE_FIELDS:
            current_val = g.get(field, 0)
            delta_field = DELTA_FIELD_MAP.get(field, f"new_{field}")

            if is_new_to_pool:
                # 首次入池：暂不计算增量，等下次有了历史数据再算
                delta_game[field] = current_val
                delta_game[f"prev_{field}"] = None  # 标记无历史
                delta_game[delta_field] = 0
            else:
                prev_val = prev.get(field, 0)
                delta_game[field] = current_val
                delta_game[f"prev_{field}"] = prev_val
                delta_game[delta_field] = current_val - prev_val

        # 状态标记
        delta_game["is_new_to_pool"] = is_new_to_pool
        delta_game["is_first_day"] = is_first_day

        if is_new_to_pool:
            new_to_pool_count += 1

        # 首日下载记录（昨日累计=0，今天的下载视为首日表现）
        if is_first_day and delta_game.get("new_downloads", 0) > 0:
            first_day_games.append({
                "rank": 0,  # 稍后填充
                "id": gid,
                "title": delta_game["title"],
                "score": delta_game.get("score"),
                "first_day_downloads": delta_game["new_downloads"],
                "first_day_fans": delta_game.get("new_fans", 0),
                "first_day_reviews": delta_game.get("new_reviews", 0),
                "download_count": delta_game["download_count"],
            })

        # 计算广告嫌疑信号（仅对非首次入池游戏评估）
        if not is_new_to_pool:
            delta_game["ad_signals"] = compute_ad_signals(delta_game)
        else:
            delta_game["ad_signals"] = {
                "ad_score": 0, "ad_level": "⏭ 首次入池暂不评估",
                "review_rate_per_10k_dl": None, "review_flag": "⏭ 首次入池",
                "follow_rate_pct": None, "follow_flag": "⏭ 首次入池",
                "growth_rate_pct": None, "growth_flag": "⏭ 首次入池",
            }

        delta_games.append(delta_game)

    # 按新增下载量降序排列（首次入池游戏 new_downloads=0 排到后面）
    delta_games.sort(key=lambda g: g.get("new_downloads", 0), reverse=True)

    # 重新编号（主榜）
    for i, g in enumerate(delta_games):
        g["rank"] = i + 1

    # 首日下载游戏按首日下载量排序
    first_day_games.sort(key=lambda g: g["first_day_downloads"], reverse=True)
    for i, g in enumerate(first_day_games):
        g["rank"] = i + 1

    if top_n:
        delta_games = delta_games[:top_n]

    return {
        "week_start": last_snapshot.get("date", ""),
        "week_end": this_snapshot.get("date", ""),
        "platform": this_snapshot.get("platform", ""),
        "fetched_at": datetime.now().isoformat(),
        "total_games": len(delta_games),
        "new_to_pool": new_to_pool_count,  # 首次进入游戏池（无历史数据，暂不计算增量）
        "first_day_count": len(first_day_games),  # 首日有下载的游戏
        "total_new_downloads": sum(g.get("new_downloads", 0) for g in delta_games if not g.get("is_new_to_pool")),
        "total_new_reviews": sum(g.get("new_reviews", 0) for g in delta_games if not g.get("is_new_to_pool")),
        "total_first_day_downloads": sum(g["first_day_downloads"] for g in first_day_games),
        "games": delta_games,
        "first_day_games": first_day_games,  # 首日下载详情
    }


# ── 输出 ──────────────────────────────────────────────────
def save_delta(delta: dict, week_end: str):
    """保存增量数据到 JSON 和 CSV"""
    DELTAS_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = DELTAS_DIR / f"{week_end}_weekly.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(delta, f, ensure_ascii=False, indent=2)

    # CSV（只输出 games 列表）
    csv_path = DELTAS_DIR / f"{week_end}_weekly.csv"
    games = delta.get("games", [])
    if games:
        # CSV 字段顺序
        csv_fields = [
            "rank", "id", "title", "score",
            "download_count", "prev_download_count", "new_downloads",
            "fans_count", "prev_fans_count", "new_fans",
            "review_count", "prev_review_count", "new_reviews",
            "reserve_count", "prev_reserve_count", "new_reserves",
            "ad_score", "ad_level",
        ]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            for g in games:
                row = {k: g.get(k, "") for k in csv_fields}
                ad = g.get("ad_signals", {})
                row["ad_score"] = ad.get("ad_score", "")
                row["ad_level"] = ad.get("ad_level", "")
                writer.writerow(row)

    return json_path, csv_path


# ── 主入口 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TapTap 周新增数据计算",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 delta.py                                   # 自动匹配最近两周
  python3 delta.py --this 2026-08-16 --last 2026-08-09 # 手动指定
  python3 delta.py --top 600                         # 只保留前 600 名
  python3 delta.py --all-weeks                       # 对全部周批量计算
        """,
    )
    parser.add_argument("--this", type=str, default=None, dest="this_week", help="本周日期 (YYYY-MM-DD)")
    parser.add_argument("--last", type=str, default=None, dest="last_week", help="上周日期 (YYYY-MM-DD)")
    parser.add_argument("--top", "-n", type=int, default=None, help="只保留前 N 名")
    parser.add_argument("--all-weeks", action="store_true", help="对所有连续周批量计算")
    parser.add_argument("--source", type=str, default="rankings", help="数据源: rankings(主站) / tapmaker (Maker)")
    parser.add_argument("--list-weeks", action="store_true", help="列出所有有快照的周")

    args = parser.parse_args()

    # 根据数据源切换路径
    global RANKINGS_DIR, DELTAS_DIR
    if args.source == "tapmaker":
        RANKINGS_DIR = ROOT / "data" / "tapmaker_rankings"
        DELTAS_DIR = ROOT / "data" / "tapmaker_deltas"
    elif args.source == "rankings":
        pass  # 默认
    else:
        print(f"❌ 未知数据源: {args.source}")
        sys.exit(1)

    available = find_available_weeks()

    if args.list_weeks:
        if available:
            print(f"可用快照 ({len(available)} 周):")
            for w in available:
                snap = load_snapshot(w)
                n = len(snap.get("games", [])) if snap else "?"
                print(f"  {w}  ({n} 款游戏)")
        else:
            print("❌ 没有找到任何快照数据")
            print("   请先运行: python3 crawler.py --all")
        return

    # 批量模式
    if args.all_weeks:
        if len(available) < 2:
            print("❌ 至少需要 2 周的快照数据才能计算增量")
            print(f"   当前: {len(available)} 周")
            return

        print(f"📊 批量处理 {len(available) - 1} 个周期...")
        for i in range(1, len(available)):
            this_date = available[i]
            last_date = available[i - 1]
            _process_week(this_date, last_date, args.top)
        return

    # 自动匹配最近两周
    if not args.this_week or not args.last_week:
        if len(available) < 2:
            print("❌ 至少需要 2 周的快照数据，当前只有", len(available))
            return
        this_date = args.this_week or available[-1]
        last_date = args.last_week or available[-2]
    else:
        this_date = args.this_week
        last_date = args.last_week

    _process_week(this_date, last_date, args.top)


def _process_week(this_date: str, last_date: str, top_n: Optional[int]):
    """处理单周计算"""
    print("=" * 60)
    print(f"📊 计算周增量: {last_date} → {this_date}")

    this_snap = load_snapshot(this_date)
    last_snap = load_snapshot(last_date)

    if not this_snap:
        print(f"  ❌ 找不到本周快照: {this_date}")
        return
    if not last_snap:
        print(f"  ❌ 找不到上周快照: {last_date}")
        return

    this_count = len(this_snap.get("games", []))
    last_count = len(last_snap.get("games", []))
    print(f"  本周: {this_count} 款游戏, 上周: {last_count} 款")

    delta = compute_delta(this_snap, last_snap, top_n)
    json_path, csv_path = save_delta(delta, this_date)

    # 摘要
    top5 = delta["games"][:5]
    print(f"\n  📋 结果摘要:")
    print(f"  总游戏数: {delta['total_games']}")
    print(f"  首次入池: {delta['new_to_pool']} 款 (无历史数据，增量暂记为 0)")
    print(f"  首日下载: {delta['first_day_count']} 款 (昨日累计=0，今日首日有下载)")
    print(f"  日总新增下载: {delta['total_new_downloads']:,} (不含首次入池)")
    print(f"  日总新增评论: {delta['total_new_reviews']:,}")
    if delta['total_first_day_downloads'] > 0:
        print(f"  首日下载总量: {delta['total_first_day_downloads']:,}")

    # 广告嫌疑统计
    ad_games = [g for g in delta["games"] if not g.get("is_new_to_pool")]
    high_ad = [g for g in ad_games if g.get("ad_signals", {}).get("ad_score", 0) >= 70]
    mid_ad = [g for g in ad_games if 40 <= g.get("ad_signals", {}).get("ad_score", 0) < 70]
    print(f"  🔴 高概率广告: {len(high_ad)} 款 | 🟡 可能有广告: {len(mid_ad)} 款")

    print(f"\n  🏆 日新增下载 TOP 5:")
    for g in top5:
        new_dl = g.get("new_downloads", 0)
        tag = " [首次入池]" if g.get("is_new_to_pool") else ""
        ad = g.get("ad_signals", {})
        print(f"  #{g['rank']:>3} {g['title']:<20s} +{new_dl:>12,}{tag}  [{ad.get('ad_level', '')}]")

    # 首日下载 TOP 5
    if delta["first_day_games"]:
        print(f"\n  🆕 首日下载 TOP 5:")
        for g in delta["first_day_games"][:5]:
            print(f"  #{g['rank']:>3} {g['title']:<20s} 首日 +{g['first_day_downloads']:>12,}")

    # 广告嫌疑 TOP 5
    ad_sorted = sorted(ad_games, key=lambda g: g.get("ad_signals", {}).get("ad_score", 0), reverse=True)
    print(f"\n  🔍 广告嫌疑最高 TOP 5:")
    for g in ad_sorted[:5]:
        ad = g.get("ad_signals", {})
        if ad.get("ad_score", 0) > 0:
            flags = []
            for f in ["review_flag", "follow_flag", "growth_flag"]:
                v = ad.get(f, "")
                if v and "⏭" not in v:
                    flags.append(v)
            flag_str = " | ".join(flags) if flags else "数据不足"
            print(f"  #{g['rank']:>3} {g['title']:<20s} ad_score={ad.get('ad_score',0):>3}  {flag_str}")

    print(f"\n  💾 已保存: {json_path.name}")
    print(f"  💾 已保存: {csv_path.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
