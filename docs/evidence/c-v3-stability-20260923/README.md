# C 实时抓取与稳定性抽检

被测版本：`d795fffbc3aa3ee5d6412c1e43d420e7afebdd0a`（A PR #27）。开始 UTC 2026-09-23T01:28:22.659381+00:00；观测约 5.4 分钟。
本次只测试，无生产代码、算法、依赖或数据库结构修改。结果代表此时段小样本，不是并发压力测试或长期稳定性保证。

## 方法
- 600519 / 000001 / 300750，3轮串行抽检，轮间15秒。每轮直接调用正式 Provider 获取基本信息、qfq日线和新闻；直接 Provider 抓取绕过项目 MySQL 行情缓存。
- 行情固定完整交易日区间2026-09-01～2026-09-22，检查代码、日期排序/唯一性、有限数值、OHLC关系和成交量；保存逐轮原始标准化响应及哈希。
- 正式 API 另测搜索、基本信息、K线、评分、健康、历史回测及历史报告。API走正式缓存机制，不把这些请求全部算作重新抓取上游。K线接口会为最小行数要求扩展窗口。
- 额外运行一次全市场目录同步、一次真实默认 AI 分析；三股票×MA/MACD六组检验直接计算、POST、GET完整C结果、新建MySQL连接回读。

## 结果
| 测试层 | 成功/总数 | 中位耗时 | P95耗时 | 最慢 |
|---|---:|---:|---:|---:|
| 真实上游抓取 | 22/27 | 4.016s | 11.094s | 11.156s |
| 正式 API | 48/48 | 0.031s | 9.344s | 9.562s |
| 目录/默认AI | 0/2 | 22.149s | 33.218s | 33.218s |

六组量化一致性：6/6通过；全部权益曲线299点。

### 失败或波动
- 第2轮 600519_news：StockDataProviderError，AKShare news request failed for 600519: AKShare call exceeded 0.5s（4.016秒）。
- 第3轮 600519_info：StockDataProviderError，AKShare info request failed for 600519: AKShare info request failed for 600519: AKShare call exceeded 0.5s (delayed-host fallback also failed: ReadTimeout: HTTPSConnectionPool(host='push2delay.eastmoney.com', port=443): Read timed out. (read timeout=3.0)) (Tencent quote fallback also failed: ReadTimeout: HTTPSConnectionPool(host='qt.gtimg.cn', port=443): Read timed out. (read timeout=3.0))（11.156秒）。
- 第3轮 000001_info：StockDataProviderError，AKShare info request failed for 000001: AKShare info request failed for 000001: AKShare call exceeded 0.5s (delayed-host fallback also failed: ReadTimeout: HTTPSConnectionPool(host='push2delay.eastmoney.com', port=443): Read timed out. (read timeout=3.0)) (Tencent quote fallback also failed: ReadTimeout: HTTPSConnectionPool(host='qt.gtimg.cn', port=443): Read timed out. (read timeout=3.0))（11.078秒）。
- 第3轮 000001_kline：StockDataProviderError，AKShare request failed for 000001: AKShare call exceeded 0.5s (Tencent qfq fallback also failed: ReadTimeout: HTTPSConnectionPool(host='web.ifzq.gtimg.cn', port=443): Read timed out. (read timeout=3.0))（11.094秒）。
- 第3轮 300750_news：StockDataProviderError，AKShare news request failed for 300750: too many in-flight AKShare calls（1.5秒）。
- 第4轮 catalog_sync：RuntimeError，HTTP 502; {'code': 50001, 'message': 'data provider error', 'data': None}（33.218秒）。
- 第4轮 default_ai：RuntimeError，HTTP 502; {'code': 50001, 'message': 'data provider error', 'data': None}（11.079秒）。

### 数据来源与复现边界
- 上游允许东财/腾讯自动后备。源切换可能改变精度及 amount、turnover_rate、change_pct；这些差异不能直接认定为量化算法漂移。
- 三轮标准化行情完整哈希保持相同：{"600519": false, "000001": false, "300750": false}。相同数据源内的一致性与跨源差异应分别看待。
- 对比旧MA #12与本次MA #26：输入字段差异1980处，总收益小数差值3.57295885434e-07。例如旧价1434.219、新价1434.22，并出现原先null的成交额/换手率。这是输入变化；两次结果各自绑定的快照不应混用。
- 搜索读本地完整目录，因此搜索正常不能证明每个实时供应商都稳定。
- 普通前端请求10秒超时，而服务可能还在等待源后备；接口耗时接近或超过10秒时，用户仍可能看见暂时失败。

完整本机观察、抓取行情、响应与脚本：`C:/Users/15149/Desktop/qproject/.codex-task/v3-stability-20260923/`。

## 本轮结论

本地搜索、缓存接口和数值链路正常，但全实时链路未通过稳定性抽检。27次直接抓取仅22次成功，失败包含基本信息/日线/新闻；新闻还在独立抓取进程出现未结束AKShare调用达到保护上限。此现象不等同于已证明线上服务线程耗尽。

目录刷新在新浪第17页经本机代理超时；旧5566条目录保留、刷新后的名称搜索仍200。默认AI本轮502/50001，失败属于数据源链路，未据此断言DeepSeek故障。旧报告#2与本轮前保存内容完全相同。

同一供应商重复抓取的已有样本哈希相同；跨供应商发生差异。详见per_source_hashes.json，单一样本不能证明稳定。

建议答辩演示优先使用已保存历史与缓存行情，明确标注来源和时间；实时取数失败如实展示。后续若要修复，优先由B/D评估挂起请求回收及超时预算，并在对齐后修改。C本次未修改算法、供应商选择或错误处理。
