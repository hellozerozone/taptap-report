#!/bin/bash
# TapTap 每日自动抓取脚本
# 每天 19:00 由 cron 触发

set -e
cd /Users/zero/WorkSpace/TAPproject

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/crawl_$TODAY.log"

{
    echo "========================================"
    echo "⏰ 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"

    echo ""
    echo "🎮 [1/4] 主站游戏爬虫 (24 榜单 + 历史追踪)..."
    /usr/bin/python3 crawler.py --all --track --date "$TODAY"

    echo ""
    echo "🔧 [2/4] TapTap Maker 游戏爬虫..."
    /usr/bin/python3 crawler_maker.py --date "$TODAY"

    echo ""
    echo "📊 [3/5] 计算主站日新增增量..."
    YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d 2>/dev/null || echo "")
    if [ -n "$YESTERDAY" ] && [ -d "data/rankings/$YESTERDAY" ]; then
        /usr/bin/python3 delta.py --this "$TODAY" --last "$YESTERDAY" --top 600
    else
        echo "  (无昨日数据，跳过)"
    fi

    echo ""
    echo "📊 [4/5] 计算 Maker 日新增增量..."
    if [ -n "$YESTERDAY" ] && [ -d "data/tapmaker_rankings/$YESTERDAY" ]; then
        /usr/bin/python3 delta.py --source tapmaker --this "$TODAY" --last "$YESTERDAY" --top 600
    else
        echo "  (无昨日 Maker 数据，跳过)"
    fi

    echo ""
    echo "📈 [5/5] 生成可视化报告..."
    /usr/bin/python3 generate_report.py
    /usr/bin/python3 generate_report_maker.py

    echo ""
    echo "========================================"
    echo "✅ 完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"

} 2>&1 | tee -a "$LOG_FILE"

# 保留最近 30 天日志
find "$LOG_DIR" -name "crawl_*.log" -mtime +30 -delete
