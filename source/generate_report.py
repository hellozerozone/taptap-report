#!/usr/bin/env python3
"""
TapTap 数据可视化报告生成器
===========================
读取 data/deltas/ 中的所有日报数据，生成包含趋势图和 TOP20 详情的 HTML 页面。

用法:
    python3 generate_report.py                    # 生成 report.html
    python3 generate_report.py -o dashboard.html  # 指定输出文件
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DELTAS_DIR = ROOT / "data" / "deltas"
OUTPUT_FILE = ROOT / "report.html"


def load_all_deltas() -> list[dict]:
    """加载所有 delta 日报数据，按日期升序"""
    if not DELTAS_DIR.exists():
        return []
    result = []
    for f in sorted(DELTAS_DIR.glob("*_weekly.json")):
        with open(f, "r") as fh:
            d = json.load(fh)
        result.append(d)
    return result


def build_html(deltas: list[dict]) -> str:
    """构建完整的 HTML 页面"""

    # ── 数据准备 ──
    dates = []
    total_dl_series = []
    total_pc_series = []
    total_mobile_series = []
    total_review_series = []
    daily_top20 = []
    daily_pc_top20 = []

    for d in deltas:
        end_date = d.get("week_end", "")
        dates.append(end_date)

        games = d.get("games", [])
        total_dl = d.get("total_new_downloads", 0)
        total_reviews = d.get("total_new_reviews", 0)
        total_pc = sum(g.get("new_pc_downloads", 0) for g in games)
        total_mobile = total_dl - total_pc

        total_dl_series.append(total_dl)
        total_pc_series.append(total_pc)
        total_mobile_series.append(total_mobile)
        total_review_series.append(total_reviews)

        # TOP20 for this day (排除首次入池游戏，它们增量为 0)
        top20 = []
        for g in games:
            if g.get("is_new_to_pool"):
                continue
            top20.append({
                "rank": 0,  # 重新编号
                "title": g["title"],
                "score": g.get("score"),
                "new_downloads": g.get("new_downloads", 0),
                "new_pc_downloads": g.get("new_pc_downloads", 0),
                "new_reviews": g.get("new_reviews", 0),
                "total_downloads": g.get("download_count", 0),
                "ad_score": g.get("ad_signals", {}).get("ad_score", 0),
                "ad_level": g.get("ad_signals", {}).get("ad_level", ""),
                "is_new_to_pool": False,
            })
            if len(top20) >= 20:
                break
        for i, g in enumerate(top20):
            g["rank"] = i + 1
        daily_top20.append({"date": end_date, "games": top20})

        # PC TOP20
        pc_top20 = []
        for g in games:
            if g.get("is_new_to_pool"):
                continue
            if g.get("new_pc_downloads", 0) <= 0:
                continue
            pc_top20.append({
                "rank": 0,
                "title": g["title"],
                "score": g.get("score"),
                "new_pc_downloads": g.get("new_pc_downloads", 0),
                "new_downloads": g.get("new_downloads", 0),
                "total_pc_downloads": g.get("pc_download_count", 0),
            })
        pc_top20.sort(key=lambda g: g["new_pc_downloads"], reverse=True)
        for i, g in enumerate(pc_top20[:20]):
            g["rank"] = i + 1
        daily_pc_top20.append({"date": end_date, "games": pc_top20[:20]})

    # ── 最新日期的摘要 ──
    latest = deltas[-1] if deltas else {}
    latest_dl = latest.get("total_new_downloads", 0)
    latest_pc = sum(g.get("new_pc_downloads", 0) for g in latest.get("games", []))
    latest_mobile = latest_dl - latest_pc
    latest_reviews = latest.get("total_new_reviews", 0)
    latest_date = latest.get("week_end", "")
    latest_new_pool = latest.get("new_to_pool", 0)
    latest_first_day = latest.get("first_day_count", 0)
    latest_first_day_dl = latest.get("total_first_day_downloads", 0)

    # ── JSON 嵌入 ──
    chart_data = {
        "dates": dates,
        "total_dl": total_dl_series,
        "total_pc": total_pc_series,
        "total_mobile": total_mobile_series,
        "total_reviews": total_review_series,
        "top20_by_date": daily_top20,
    }

    # 值单位转换：原始值是"次"，图表显示"万"
    def to_wan(vals):
        return [round(v / 10000, 2) for v in vals]

    # 首日下载数据（从 games 列表求和，保证与 total_new_downloads 口径一致：
    # 只统计 is_first_day 且计入总新增的游戏，历史文件旧版本可能有口径偏差）
    first_day_dl_series = []
    first_day_count_series = []
    for d in deltas:
        fd_sum = sum(
            g.get("new_downloads", 0)
            for g in d.get("games", [])
            if g.get("is_first_day") and not g.get("is_new_to_pool")
        )
        first_day_dl_series.append(fd_sum)
        first_day_count_series.append(d.get("first_day_count", 0))

    # 老游戏新增 = 总新增 − 新游戏首日新增
    old_games_dl_series = [
        total_dl_series[i] - first_day_dl_series[i] for i in range(len(deltas))
    ]

    chart_data_wan = {
        "dates": dates,
        "total_dl": to_wan(total_dl_series),
        "total_pc": to_wan(total_pc_series),
        "total_mobile": to_wan(total_mobile_series),
        "total_reviews": to_wan(total_review_series),
        "first_day_dl": to_wan(first_day_dl_series),
        "old_games_dl": to_wan(old_games_dl_series),
        "first_day_count": first_day_count_series,
        "new_to_pool": [d.get("new_to_pool", 0) for d in deltas],
    }

    # 首日下载游戏详情（最新一天）
    first_day_games_data = latest.get("first_day_games", [])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TapTap 新增下载日报</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
:root {{
    --bg: #f7f9fc; --surface: #ffffff; --text: #1a1a2e; --text2: #6b7280;
    --accent: #5470C6; --accent2: #EE6666; --green: #3ba272; --border: #e5e7eb;
    --card-shadow: 0 2px 12px rgba(0,0,0,0.06);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: var(--bg); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--text); padding: 24px; display: flex; flex-direction: column; align-items: center;
}}
.container {{ width: 100%; max-width: 1200px; display: flex; flex-direction: column; gap: 20px; }}
.header {{ text-align: center; padding: 8px 0; }}
.header h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 4px; }}
.header .sub {{ font-size: 14px; color: var(--text2); }}

/* 摘要卡片 */
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
.card {{
    background: var(--surface); border-radius: 12px; padding: 20px;
    box-shadow: var(--card-shadow); text-align: center;
}}
.card .label {{ font-size: 13px; color: var(--text2); margin-bottom: 6px; }}
.card .value {{ font-size: 28px; font-weight: 700; }}
.card .unit {{ font-size: 13px; color: var(--text2); }}
.card.dl .value {{ color: var(--accent); }}
.card.pc .value {{ color: #8b5cf6; }}
.card.mobile .value {{ color: var(--green); }}
.card.review .value {{ color: var(--accent2); }}

/* 图表面板 */
.panel {{
    background: var(--surface); border-radius: 12px; padding: 20px;
    box-shadow: var(--card-shadow);
}}
.panel h3 {{ font-size: 16px; margin-bottom: 12px; color: var(--text); }}
.chart {{ width: 100%; height: 420px; }}

/* 视图切换按钮 */
.toggle-group {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.toggle-btn {{
    padding: 6px 16px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--surface); cursor: pointer; font-size: 13px; color: var(--text2);
    transition: all 0.2s;
}}
.toggle-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* TOP20 表格 */
table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
thead th {{
    padding: 10px 12px; font-weight: 600; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.3px; color: var(--text2); border-bottom: 2px solid var(--border);
    text-align: right; white-space: nowrap;
}}
thead th.left {{ text-align: left; }}
tbody td {{
    padding: 9px 12px; border-bottom: 1px solid var(--border); text-align: right;
    white-space: nowrap;
}}
tbody td.left {{ text-align: left; }}
tbody tr:hover td {{ background: #f0f4ff; }}
.rank-badge {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%; font-size: 11px; font-weight: 700;
}}
.rank-1 {{ background: #fef3c7; color: #b45309; }}
.rank-2 {{ background: #f1f5f9; color: #64748b; }}
.rank-3 {{ background: #fff7ed; color: #ea580c; }}
.ad-dot {{ font-size: 11px; }}

/* 日期选择器 */
.date-selector {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
.date-tag {{
    padding: 5px 14px; border-radius: 16px; font-size: 12px; cursor: pointer;
    border: 1px solid var(--border); background: var(--surface); color: var(--text2);
    transition: all 0.2s;
}}
.date-tag.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

.note {{
    padding: 12px 16px; background: #f8f9fa; border-left: 4px solid var(--accent);
    color: var(--text2); font-size: 13px; border-radius: 0 4px 4px 0; line-height: 1.6;
}}
</style>
</head>
<body>

<div class="container">

<div class="header">
    <h1>📊 TapTap 每日新增下载分析</h1>
    <div class="sub">数据范围: {dates[0] if dates else '—'} 至 {dates[-1] if dates else '—'} · 前 600 名游戏 · 每日自动更新</div>
</div>

<!-- 摘要卡片 -->
<div class="cards">
    <div class="card dl">
        <div class="label">📥 日新增下载</div>
        <div class="value">{latest_dl/10000:.1f}<span class="unit"> 万</span></div>
    </div>
    <div class="card mobile">
        <div class="label">📱 手游新增</div>
        <div class="value">{latest_mobile/10000:.1f}<span class="unit"> 万</span></div>
    </div>
    <div class="card pc">
        <div class="label">🖥 PC 新增</div>
        <div class="value">{latest_pc/10000:.1f}<span class="unit"> 万</span></div>
    </div>
    <div class="card review">
        <div class="label">💬 新增评论</div>
        <div class="value">{latest_reviews/10000:.1f}<span class="unit"> 万</span></div>
    </div>
    <div class="card" style="--card-color: #f59e0b;">
        <div class="label">🆕 首日下载</div>
        <div class="value" style="color: #f59e0b;">{latest_first_day_dl/10000:.1f}<span class="unit"> 万</span></div>
        <div class="unit">{latest_first_day} 款新游戏</div>
    </div>
    <div class="card" style="--card-color: #8b5cf6;">
        <div class="label">📦 首次入池</div>
        <div class="value" style="color: #8b5cf6;">{latest_new_pool}<span class="unit"> 款</span></div>
        <div class="unit">待下次有历史数据后计算</div>
    </div>
</div>

<!-- 趋势图 -->
<div class="panel">
    <h3>📈 每日新增趋势</h3>
    <div class="toggle-group">
        <button class="toggle-btn active" onclick="switchView('oldnew')">老游戏 / 新游戏 拆分</button>
        <button class="toggle-btn" onclick="switchView('split')">手游 / PC 拆分</button>
    </div>
    <div id="trendChart" class="chart"></div>
</div>

<!-- 评论趋势 -->
<div class="panel">
    <h3>💬 每日新增评论趋势</h3>
    <div id="reviewChart" class="chart"></div>
</div>

<!-- TOP20 表格 -->
<div class="panel">
    <h3>🏆 每日新增下载 TOP 20</h3>
    <div class="date-selector" id="dateSelector"></div>
    <div style="overflow-x: auto;">
        <table>
            <thead>
                <tr>
                    <th class="left">#</th><th class="left">游戏名称</th><th>评分</th>
                    <th>总新增下载</th><th>手游下载</th><th>PC下载</th>
                    <th>新增评论</th><th>累计下载</th><th>广告</th>
                </tr>
            </thead>
            <tbody id="top20Body"></tbody>
        </table>
    </div>
</div>

<!-- PC 新增下载 TOP20 -->
<div class="panel">
    <h3>🖥 PC 新增下载 TOP 20</h3>
    <div class="date-selector" id="pcDateSelector"></div>
    <div style="overflow-x: auto;">
        <table>
            <thead>
                <tr>
                    <th class="left">#</th><th class="left">游戏名称</th><th>评分</th>
                    <th>PC 新增</th><th>总新增</th><th>PC 占比</th>
                    <th>PC 累计下载</th>
                </tr>
            </thead>
            <tbody id="pcTop20Body"></tbody>
        </table>
    </div>
    <div id="noPcData" style="text-align:center;padding:20px;color:var(--text2);display:none;">当日无 PC 新增数据</div>
</div>

<!-- 首日下载表格 -->
<div class="panel">
    <h3>🆕 首日下载游戏（昨日累计=0，今日首次有下载）</h3>
    <div style="overflow-x: auto;">
        <table>
            <thead>
                <tr>
                    <th class="left">#</th><th class="left">游戏名称</th><th>评分</th>
                    <th>首日下载</th><th>首日关注</th><th>首日评论</th>
                    <th>当前累计下载</th>
                </tr>
            </thead>
            <tbody id="firstDayBody"></tbody>
        </table>
    </div>
    <div id="noFirstDay" style="text-align:center;padding:20px;color:var(--text2);display:none;">今日无首日下载游戏</div>
</div>

<div class="note">
    <strong>💡 数据说明：</strong>每日新增 = 当日累计数据 − 前一日累计数据。手游下载 = 总下载 − PC 下载。
    覆盖 TapTap 24 个榜单分类去重后的约 1000 款游戏。<br>
    <strong>老游戏新增</strong>：已有累计下载记录的游戏当日新增下载；<strong>新游戏首日新增</strong>：昨日累计下载 = 0、今日首次产生下载的游戏（首日下载），两者合计 = 当日总新增下载。<br>
    <strong>首次入池</strong>：首次出现在快照中的游戏，因无历史数据，增量暂记为 0，待下次自动计算。<br>
    广告评分基于评论率、关注转化率和增长率异常综合判定。
</div>

</div>

<script>
const DATA = {json.dumps(chart_data_wan, ensure_ascii=False)};
const TOP20_DATA = {json.dumps(daily_top20, ensure_ascii=False)};
const PC_TOP20_DATA = {json.dumps(daily_pc_top20, ensure_ascii=False)};
const FIRST_DAY_DATA = {json.dumps(first_day_games_data, ensure_ascii=False)};

let currentView = 'oldnew';
let trendChart, reviewChart;

// ── 趋势图 ──
function initTrendChart() {{
    trendChart = echarts.init(document.getElementById('trendChart'));
    reviewChart = echarts.init(document.getElementById('reviewChart'));
    renderTrendChart();
    renderReviewChart();
}}

function renderTrendChart() {{
    let series;
    if (currentView === 'oldnew') {{
        // 老游戏 / 新游戏 拆分：堆叠柱 + 柱顶标注总新增
        series = [
            {{ name: '老游戏新增', type: 'bar', stack: 'total', data: DATA.old_games_dl,
               itemStyle: {{ color: '#5470C6', borderRadius: [4,4,0,0] }} }},
            {{ name: '新游戏首日新增', type: 'bar', stack: 'total', data: DATA.first_day_dl,
               itemStyle: {{ color: '#f59e0b', borderRadius: [4,4,0,0] }},
               label: {{
                   show: true, position: 'top', fontWeight: 700, fontSize: 11, color: '#1a1a2e',
                   formatter: function(params) {{
                       let total = DATA.old_games_dl[params.dataIndex] + DATA.first_day_dl[params.dataIndex];
                       return total > 0 ? total.toFixed(1) + ' 万' : '';
                   }}
               }} }},
        ];
    }} else {{
        series = [
            {{ name: '手游下载', type: 'bar', stack: 'total', data: DATA.total_mobile, itemStyle: {{ color: '#3ba272' }} }},
            {{ name: 'PC下载', type: 'bar', stack: 'total', data: DATA.total_pc, itemStyle: {{ color: '#8b5cf6' }} }},
        ];
    }}

    let option = {{
        tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }},
            formatter: function(params) {{
                let s = params[0].axisValue + '<br/>';
                let sum = 0;
                params.forEach(p => {{ s += p.marker + ' ' + p.seriesName + ': ' + p.value + ' 万<br/>'; sum += Number(p.value); }});
                if (params.length > 1) s += '<b>合计: ' + sum.toFixed(2) + ' 万</b>';
                return s;
            }}
        }},
        legend: {{ data: series.map(s => s.name), top: 'bottom' }},
        grid: {{ left: '5%', right: '5%', bottom: '12%', containLabel: true }},
        xAxis: {{ type: 'category', data: DATA.dates, axisLabel: {{ rotate: 45 }} }},
        yAxis: {{ type: 'value', name: '新增下载 (万/日)', nameTextStyle: {{ fontWeight: 'bold' }} }},
        series: series,
    }};
    trendChart.setOption(option, true);
}}

function renderReviewChart() {{
    let option = {{
        tooltip: {{ trigger: 'axis' }},
        grid: {{ left: '5%', right: '5%', bottom: '12%', containLabel: true }},
        xAxis: {{ type: 'category', data: DATA.dates, axisLabel: {{ rotate: 45 }} }},
        yAxis: {{ type: 'value', name: '新增评论 (万/日)', nameTextStyle: {{ fontWeight: 'bold', color: '#EE6666' }} }},
        series: [{{
            name: '新增评论', type: 'line', smooth: true, symbol: 'circle', symbolSize: 8,
            data: DATA.total_reviews, itemStyle: {{ color: '#EE6666' }},
            lineStyle: {{ width: 3 }},
        }}],
    }};
    reviewChart.setOption(option, true);
}}

function switchView(view) {{
    currentView = view;
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    renderTrendChart();
}}

// ── TOP20 表格 ──
function renderTop20(dateIdx) {{
    if (!dateIdx) dateIdx = TOP20_DATA.length - 1;
    let day = TOP20_DATA[dateIdx];
    if (!day) return;

    let tbody = document.getElementById('top20Body');
    let rows = day.games.map(g => {{
        let mobileDL = g.new_downloads - g.new_pc_downloads;
        let rankClass = g.rank <= 3 ? ' rank-' + g.rank : '';
        let adIcon = '';
        if (g.ad_score >= 70) adIcon = '<span class="ad-dot" title="高概率广告导入">🔴</span>';
        else if (g.ad_score >= 40) adIcon = '<span class="ad-dot" title="可能有广告">🟡</span>';

        return `<tr>
            <td class="left"><span class="rank-badge ${{rankClass}}">${{g.rank}}</span></td>
            <td class="left">${{g.title}}</td>
            <td>${{g.score != null ? g.score.toFixed(1) : '—'}}</td>
            <td style="font-weight:700">${{(g.new_downloads/10000).toFixed(1)}} 万</td>
            <td>${{(mobileDL/10000).toFixed(1)}} 万</td>
            <td>${{(g.new_pc_downloads/10000).toFixed(1)}} 万</td>
            <td>${{g.new_reviews.toLocaleString()}}</td>
            <td>${{(g.total_downloads/10000).toFixed(0)}} 万</td>
            <td>${{adIcon}}</td>
        </tr>`;
    }}).join('');

    tbody.innerHTML = rows;

    // 更新日期选择器
    let sel = document.getElementById('dateSelector');
    sel.innerHTML = TOP20_DATA.map((d, i) => {{
        let cls = i === dateIdx ? 'date-tag active' : 'date-tag';
        return `<span class="${{cls}}" onclick="renderTop20(${{i}})">${{d.date}}</span>`;
    }}).join('');
}}

// ── PC TOP20 渲染 ──
function renderPcTop20(dateIdx) {{
    if (!dateIdx) dateIdx = PC_TOP20_DATA.length - 1;
    let day = PC_TOP20_DATA[dateIdx];
    let tbody = document.getElementById('pcTop20Body');
    let noData = document.getElementById('noPcData');
    if (!day || day.games.length === 0) {{
        noData.style.display = 'block';
        tbody.innerHTML = '';
        return;
    }}
    noData.style.display = 'none';
    let rows = day.games.map(g => {{
        let pcRatio = g.new_downloads > 0 ? (g.new_pc_downloads / g.new_downloads * 100).toFixed(1) + '%' : '—';
        return `<tr>
            <td class="left"><span class="rank-badge">${{g.rank}}</span></td>
            <td class="left">${{g.title}}</td>
            <td>${{g.score != null ? g.score.toFixed(1) : '—'}}</td>
            <td style="font-weight:700">${{g.new_pc_downloads.toLocaleString()}}</td>
            <td>${{g.new_downloads.toLocaleString()}}</td>
            <td>${{pcRatio}}</td>
            <td>${{(g.total_pc_downloads).toLocaleString()}}</td>
        </tr>`;
    }}).join('');
    tbody.innerHTML = rows;

    // Update date selector
    let sel = document.getElementById('pcDateSelector');
    sel.innerHTML = PC_TOP20_DATA.map((d, i) => {{
        let cls = i === dateIdx ? 'date-tag active' : 'date-tag';
        return `<span class="${{cls}}" onclick="renderPcTop20(${{i}})">${{d.date}}</span>`;
    }}).join('');
}}

// ── 首日下载渲染 ──
function renderFirstDay() {{
    let tbody = document.getElementById('firstDayBody');
    let noData = document.getElementById('noFirstDay');
    if (!FIRST_DAY_DATA || FIRST_DAY_DATA.length === 0) {{
        noData.style.display = 'block';
        return;
    }}
    noData.style.display = 'none';
    let rows = FIRST_DAY_DATA.map(g => {{
        return `<tr>
            <td class="left"><span class="rank-badge">${{g.rank}}</span></td>
            <td class="left">${{g.title}}</td>
            <td>${{g.score != null ? g.score.toFixed(1) : '—'}}</td>
            <td style="font-weight:700">${{(g.first_day_downloads/10000).toFixed(2)}} 万</td>
            <td>${{g.first_day_fans.toLocaleString()}}</td>
            <td>${{g.first_day_reviews.toLocaleString()}}</td>
            <td>${{(g.download_count/10000).toFixed(0)}} 万</td>
        </tr>`;
    }}).join('');
    tbody.innerHTML = rows;
}}

// ── 初始化 ──
initTrendChart();
renderTop20(TOP20_DATA.length - 1);
renderPcTop20(PC_TOP20_DATA.length - 1);
renderFirstDay();
window.addEventListener('resize', () => {{ trendChart && trendChart.resize(); reviewChart && reviewChart.resize(); }});
</script>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="TapTap 数据可视化报告生成器")
    parser.add_argument("-o", "--output", type=str, default=str(OUTPUT_FILE), help="输出文件路径")
    args = parser.parse_args()

    deltas = load_all_deltas()
    if not deltas:
        print("❌ 没有找到 delta 数据，请先运行 delta.py")
        return

    print(f"📊 加载 {len(deltas)} 天日报数据")
    for d in deltas:
        print(f"  {d.get('week_end', '?')}: {d['total_games']} 款游戏, "
              f"新增下载 {d['total_new_downloads']:,}")

    html = build_html(deltas)

    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"\n✅ 报告已生成: {out_path} ({len(html):,} bytes)")
    print(f"   浏览器打开: open {out_path}")


if __name__ == "__main__":
    main()
