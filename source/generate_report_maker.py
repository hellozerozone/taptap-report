#!/usr/bin/env python3
"""
TapTap Maker 数据可视化报告生成器
==================================
读取 data/tapmaker_deltas/ 中的 Maker 日报数据，生成 Maker 专用报告。

用法:
    python3 generate_report_maker.py
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DELTAS_DIR = ROOT / "data" / "tapmaker_deltas"
OUTPUT_FILE = ROOT / "maker_report.html"


def load_all_deltas() -> list[dict]:
    if not DELTAS_DIR.exists():
        return []
    result = []
    for f in sorted(DELTAS_DIR.glob("*_weekly.json")):
        with open(f, "r") as fh:
            result.append(json.load(fh))
    return result


def build_html(deltas: list[dict]) -> str:
    dates = []
    total_dl_series = []
    total_review_series = []
    daily_top20 = []
    new_pool_series = []
    first_day_count_series = []
    first_day_dl_series = []

    for d in deltas:
        end_date = d.get("week_end", "")
        dates.append(end_date)
        games = d.get("games", [])
        total_dl = d.get("total_new_downloads", 0)
        total_reviews = d.get("total_new_reviews", 0)
        total_dl_series.append(total_dl)
        total_review_series.append(total_reviews)
        new_pool_series.append(d.get("new_to_pool", 0))
        first_day_count_series.append(d.get("first_day_count", 0))
        first_day_dl_series.append(d.get("total_first_day_downloads", 0))

        # TOP20
        top20 = []
        for g in games:
            if g.get("is_new_to_pool"):
                continue
            top20.append({
                "rank": 0, "title": g["title"], "score": g.get("score"),
                "new_downloads": g.get("new_downloads", 0),
                "new_reviews": g.get("new_reviews", 0),
                "new_fans": g.get("new_fans", 0),
                "total_downloads": g.get("download_count", 0),
            })
            if len(top20) >= 20:
                break
        for i, g in enumerate(top20):
            g["rank"] = i + 1
        daily_top20.append({"date": end_date, "games": top20})

    # 最新摘要
    latest = deltas[-1] if deltas else {}
    latest_dl = latest.get("total_new_downloads", 0)
    latest_reviews = latest.get("total_new_reviews", 0)
    latest_new_pool = latest.get("new_to_pool", 0)
    latest_first_day = latest.get("first_day_count", 0)
    latest_first_day_dl = latest.get("total_first_day_downloads", 0)
    first_day_games_data = latest.get("first_day_games", [])

    # 单位转换：Maker 数据量小，用"次"或"千"
    def to_k(vals):
        return [round(v / 1000, 1) for v in vals]

    chart_data = {
        "dates": dates,
        "total_dl": to_k(total_dl_series),
        "total_reviews": to_k(total_review_series),
        "new_pool": new_pool_series,
        "first_day_count": first_day_count_series,
        "first_day_dl": to_k(first_day_dl_series),
    }

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TapTap Maker 新增下载日报</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
:root {{ --bg: #f7f9fc; --surface: #fff; --text: #1a1a2e; --text2: #6b7280;
    --accent: #5470C6; --green: #3ba272; --orange: #f59e0b; --border: #e5e7eb;
    --card-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--text); padding: 24px; display: flex; flex-direction: column; align-items: center; }}
.container {{ width: 100%; max-width: 1100px; display: flex; flex-direction: column; gap: 20px; }}
.header {{ text-align: center; padding: 8px 0; }}
.header h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 4px; }}
.header .sub {{ font-size: 14px; color: var(--text2); }}

.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
.card {{ background: var(--surface); border-radius: 12px; padding: 20px;
    box-shadow: var(--card-shadow); text-align: center; }}
.card .label {{ font-size: 13px; color: var(--text2); margin-bottom: 6px; }}
.card .value {{ font-size: 28px; font-weight: 700; }}
.card .unit {{ font-size: 13px; color: var(--text2); }}

.panel {{ background: var(--surface); border-radius: 12px; padding: 20px; box-shadow: var(--card-shadow); }}
.panel h3 {{ font-size: 16px; margin-bottom: 12px; }}
.chart {{ width: 100%; height: 380px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
thead th {{ padding: 10px 12px; font-weight: 600; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.3px; color: var(--text2); border-bottom: 2px solid var(--border);
    text-align: right; white-space: nowrap; }}
thead th.left {{ text-align: left; }}
tbody td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); text-align: right; white-space: nowrap; }}
tbody td.left {{ text-align: left; }}
tbody tr:hover td {{ background: #f0f4ff; }}
.rank-badge {{ display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%; font-size: 11px; font-weight: 700; }}
.rank-1 {{ background: #fef3c7; color: #b45309; }}
.rank-2 {{ background: #f1f5f9; color: #64748b; }}
.rank-3 {{ background: #fff7ed; color: #ea580c; }}

.date-selector {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
.date-tag {{ padding: 5px 14px; border-radius: 16px; font-size: 12px; cursor: pointer;
    border: 1px solid var(--border); background: var(--surface); color: var(--text2); }}
.date-tag.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

.note {{ padding: 12px 16px; background: #f8f9fa; border-left: 4px solid var(--accent);
    color: var(--text2); font-size: 13px; border-radius: 0 4px 4px 0; line-height: 1.6; }}
</style>
</head>
<body>

<div class="container">

<div class="header">
    <h1>🔧 TapTap Maker 每日新增下载分析</h1>
    <div class="sub">数据范围: {dates[0] if dates else '—'} 至 {dates[-1] if dates else '—'} · Maker 游戏约 5000 款 · 每日自动更新</div>
</div>

<div class="cards">
    <div class="card"><div class="label">📥 日新增下载</div>
        <div class="value" style="color:var(--accent)">{latest_dl/1000:.1f}<span class="unit"> 千</span></div></div>
    <div class="card"><div class="label">💬 日新增评论</div>
        <div class="value" style="color:#EE6666">{latest_reviews:,}<span class="unit"> 条</span></div></div>
    <div class="card"><div class="label">🆕 首次入池</div>
        <div class="value" style="color:#8b5cf6">{latest_new_pool}<span class="unit"> 款</span></div>
        <div class="unit">新进入追踪池</div></div>
    <div class="card"><div class="label">🌟 首日下载</div>
        <div class="value" style="color:var(--orange)">{latest_first_day_dl/1000:.1f}<span class="unit"> 千</span></div>
        <div class="unit">{latest_first_day} 款新游戏</div></div>
</div>

<div class="panel">
    <h3>📈 Maker 每日新增下载趋势</h3>
    <div id="dlChart" class="chart"></div>
</div>

<div class="panel">
    <h3>💬 Maker 每日新增评论趋势</h3>
    <div id="reviewChart" class="chart"></div>
</div>

<div class="panel">
    <h3>🏆 Maker 日新增下载 TOP 20</h3>
    <div class="date-selector" id="dateSelector"></div>
    <div style="overflow-x: auto;">
        <table>
            <thead><tr>
                <th class="left">#</th><th class="left">游戏名称</th><th>评分</th>
                <th>新增下载</th><th>新增关注</th><th>新增评论</th>
                <th>累计下载</th>
            </tr></thead>
            <tbody id="top20Body"></tbody>
        </table>
    </div>
</div>

<div class="panel">
    <h3>🆕 Maker 首日下载游戏 TOP 20</h3>
    <div style="overflow-x: auto;">
        <table>
            <thead><tr>
                <th class="left">#</th><th class="left">游戏名称</th><th>评分</th>
                <th>首日下载</th><th>首日关注</th><th>首日评论</th>
                <th>累计下载</th>
            </tr></thead>
            <tbody id="firstDayBody"></tbody>
        </table>
    </div>
    <div id="noFirstDay" style="text-align:center;padding:20px;color:var(--text2);display:none;">今日无首日下载游戏</div>
</div>

<div class="note">
    <strong>💡 数据说明：</strong>TapTap Maker 是用户自制游戏平台，覆盖约 5000 款游戏。
    每日新增 = 当日累计 − 前一日累计。首次入池游戏因无历史数据，增量暂记为 0。<br>
    <strong>首日下载</strong>：昨日累计 = 0、今日首次有下载的游戏。Maker 游戏量级较小（多数日新增在几百到几千）。
</div>

</div>

<script>
const DATA = {json.dumps(chart_data, ensure_ascii=False)};
const TOP20_DATA = {json.dumps(daily_top20, ensure_ascii=False)};
const FIRST_DAY_DATA = {json.dumps(first_day_games_data, ensure_ascii=False)};

let dlChart, reviewChart;

function initCharts() {{
    dlChart = echarts.init(document.getElementById('dlChart'));
    reviewChart = echarts.init(document.getElementById('reviewChart'));

    dlChart.setOption({{
        tooltip: {{ trigger: 'axis' }},
        grid: {{ left: '5%', right: '5%', bottom: '12%', containLabel: true }},
        xAxis: {{ type: 'category', data: DATA.dates, axisLabel: {{ rotate: 45 }} }},
        yAxis: {{ type: 'value', name: '新增下载 (千/日)' }},
        series: [{{ name: '新增下载', type: 'bar', data: DATA.total_dl,
            itemStyle: {{ color: '#5470C6', borderRadius: [4,4,0,0] }} }}],
    }});

    reviewChart.setOption({{
        tooltip: {{ trigger: 'axis' }},
        grid: {{ left: '5%', right: '5%', bottom: '12%', containLabel: true }},
        xAxis: {{ type: 'category', data: DATA.dates, axisLabel: {{ rotate: 45 }} }},
        yAxis: {{ type: 'value', name: '新增评论 (条/日)' }},
        series: [{{ name: '新增评论', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
            data: DATA.total_reviews, itemStyle: {{ color: '#EE6666' }}, lineStyle: {{ width: 3 }} }}],
    }});
}}

function renderTop20(dateIdx) {{
    if (!dateIdx) dateIdx = TOP20_DATA.length - 1;
    let day = TOP20_DATA[dateIdx];
    if (!day) return;
    let tbody = document.getElementById('top20Body');
    tbody.innerHTML = day.games.map(g => {{
        let rc = g.rank <= 3 ? ' rank-' + g.rank : '';
        return `<tr>
            <td class="left"><span class="rank-badge${{rc}}">${{g.rank}}</span></td>
            <td class="left">${{g.title}}</td>
            <td>${{g.score != null ? g.score.toFixed(1) : '—'}}</td>
            <td style="font-weight:700">${{g.new_downloads.toLocaleString()}}</td>
            <td>${{g.new_fans.toLocaleString()}}</td>
            <td>${{g.new_reviews.toLocaleString()}}</td>
            <td>${{(g.total_downloads/1000).toFixed(0)}} 千</td>
        </tr>`;
    }}).join('');
    document.getElementById('dateSelector').innerHTML = TOP20_DATA.map((d, i) => {{
        let cls = i === dateIdx ? 'date-tag active' : 'date-tag';
        return `<span class="${{cls}}" onclick="renderTop20(${{i}})">${{d.date}}</span>`;
    }}).join('');
}}

function renderFirstDay() {{
    let tbody = document.getElementById('firstDayBody');
    let no = document.getElementById('noFirstDay');
    if (!FIRST_DAY_DATA || FIRST_DAY_DATA.length === 0) {{ no.style.display = 'block'; return; }}
    no.style.display = 'none';
    tbody.innerHTML = FIRST_DAY_DATA.map(g => `<tr>
        <td class="left">${{g.rank}}</td>
        <td class="left">${{g.title}}</td>
        <td>${{g.score != null ? g.score.toFixed(1) : '—'}}</td>
        <td style="font-weight:700">${{g.first_day_downloads.toLocaleString()}}</td>
        <td>${{g.first_day_fans.toLocaleString()}}</td>
        <td>${{g.first_day_reviews.toLocaleString()}}</td>
        <td>${{(g.download_count/1000).toFixed(0)}} 千</td>
    </tr>`).join('');
}}

initCharts();
renderTop20(TOP20_DATA.length - 1);
renderFirstDay();
window.addEventListener('resize', () => {{ dlChart && dlChart.resize(); reviewChart && reviewChart.resize(); }});
</script>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="TapTap Maker 数据可视化报告生成器")
    parser.add_argument("-o", "--output", type=str, default=str(OUTPUT_FILE), help="输出文件路径")
    args = parser.parse_args()

    deltas = load_all_deltas()
    if not deltas:
        print("❌ 没有找到 Maker delta 数据，请先运行 delta.py --source tapmaker")
        return

    print(f"📊 加载 {len(deltas)} 天 Maker 日报数据")
    html = build_html(deltas)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"✅ 报告已生成: {args.output} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
