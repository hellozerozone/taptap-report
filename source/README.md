# 源码与数据（MIT License）

本目录包含 TapTap 每日新增报告的全部抓取代码与历史数据，每天随报告一起自动更新。

## 文件说明

| 文件 | 作用 |
|---|---|
| `crawler.py` | 主站爬虫：24 个榜单 + 掉榜游戏历史追踪 |
| `crawler_maker.py` | TapTap Maker 平台爬虫 |
| `delta.py` | 计算日新增（下载/粉丝/评论等）与广告嫌疑评分 |
| `generate_report.py` / `generate_report_maker.py` | 生成可视化 HTML 报告 |
| `run_daily.sh` | 一键流水线（爬取 → 增量 → 报告） |
| `data/` | 每日快照与增量数据 |

## data/ 结构

```
data/
├── rankings/YYYY-MM-DD/        # 主站每日榜单快照（snapshot.json 及各榜单 json）
├── tapmaker_rankings/YYYY-MM-DD/  # Maker 每日快照
├── deltas/                     # 主站每日增量（JSON + CSV）
├── tapmaker_deltas/            # Maker 每日增量
└── trend_data.{json,csv}       # 掉榜游戏追踪数据
```

## 运行

```bash
# 完整流程（默认抓当天）
./run_daily.sh

# 或分步执行
python3 crawler.py --all --track --date 2026-08-16
python3 crawler_maker.py --date 2026-08-16
python3 delta.py --this 2026-08-16 --last 2026-08-15 --top 600
python3 generate_report.py
```

依赖：Python 3.8+，`pip install requests`

数据来源：[TapTap](https://www.taptap.cn) 公开 API，仅供个人学习研究使用。
