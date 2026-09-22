# C：V3 最终 main 同步与预跑

被测生产版本：`a6c939351579076ce65b0fec6573bf72cb3cfcd9`（D 实际合并后的 main）。
执行时间：2026-09-22 深夜至 09-23 凌晨，Asia/Shanghai。

## 结论与范围

C 数值一致性验收通过。三股票 × 三组 MACD 参数在直接计算、正式 POST 路由、重建引擎/会话后的真实 MySQL GET 之间完整一致；九组 MA 保存结果到 AI 上下文、请求、报告保存与 GET 的链路通过。固定行情来自仓库 `docs/evidence/c-delivery-20260917` 的腾讯 qfq normalized 包；不把这些结果解释为实时行情或投资效果证明。

本次未修改生产代码、量化算法、接口、公共依赖或原基线哈希。`git diff 6a84901 HEAD -- backend/app/quant` 为空。C 分支先 fast-forward 到上述 main，再仅增加本目录的验收材料；证据提交 SHA 不是新的生产版本。

## 实际执行

环境：Windows，Python 3.12.10 / pandas 2.3.3 / NumPy 2.5.3。

| 检查 | 结果 |
|---|---|
| `python -m pytest tests -q` | 751 passed、1 skipped；原 pre-V3 基线守卫通过 |
| `python -m compileall -q backend scripts` | exit 0 |
| `python scripts/validate_quant_core.py` | exit 0 |
| `python scripts/validate_c_ai_history_compatibility.py --output-dir <new-dir>` | PASS（该脚本本身为 SQLite、synthetic bars、fake LLM） |
| `python scripts/validate_v3_macd.py --output-dir <new-dir>` | PASS，9 MACD + 1 MA 全量快照复演及文件哈希核对 |
| 前端 `vue-tsc --noEmit` / `vite build` | 均 exit 0，仍有既有大 chunk 提示 |
| `git diff --check` / 被测 checkout 状态 | 无错误、工作树干净 |

一个 skip 是 C strategy 入口已经支持 MACD 后，不再适用的“旧入口不支持 MACD”分支测试。pytest 另有两条依赖弃用提示，不是测试失败。

## 真实 MySQL 数值链路

`run_mysql_probes.py` 复用 main 中已审阅的 `c-v3-d22-approved-20260922/probe_backtest.py` 与 `probe_ai.py`。只在外部验收驱动中把 SQLite 引擎换为两个唯一命名的本机 MySQL 新库、更新被测 SHA 元信息并启用已有 MACD 拒绝用例。未覆盖 ai_quant，测试库保留供复核。连接凭据仅从本机原配置读取，未写入证据。

- 三只股票：600519、000001、300750。
- 区间：2025-07-04 至 2026-08-31。
- MACD：12/26/9 默认；6/13/5；20/40/12 + 资金 200000 + 成本 0.002 + 滑点 0.001。
- 九组均核对全部 C 结果的 canonical JSON（包含类型、输入哈希、订单、曲线）；GET 每组重新建立引擎/会话，禁止行情获取和量化重算；历史六项参数重 POST 结果一致。
- 五种日期缺失/null、六种非法参数均按契约拒绝，取数和保存次数为零；缺少 C strategy 支持返回 50004。
- MA 九组：默认 5/20、10/30、20/60 + 资金 200000 + 成本/滑点，核对原始数值、D 的 15 位归一化上下文、独立上下文哈希、保存与新连接回读。
- 四种损坏快照（收益、回撤、往返数、零资金）均返回 JSON 50002，LLM 调用零、报告新增零。
- MACD 解读仍按既定范围返回 HTTP 422 / 40007，LLM 调用零。

结果见 `backtest-mysql.json`、`ai-mysql.json`、`mysql-databases.json`。AI 使用测试 LLM，未调用真实供应商。AI 数值探针用当前 ORM 建表验证报告读写，不能据此代替 B 的 V1→v9 迁移链检查；回测库确实运行了正式迁移入口。

## 页面预跑

在同一未修改 main 上运行前端 5184 与后端 8124。后端真实计算、正式路由/服务/仓库、独立 MySQL；外部行情为固定包，股票基本信息为三股固定名称，新闻为空，LLM 为 `PRERUN_FIXTURE_NOT_REAL_LLM`。前端搜索和数据状态卡使用其已有 mock 开关，其余 API 走实际后端。该页面不是全实时环境，数据状态卡的日期/行数不用于数值验收。报告正文明确标注“预跑测试响应，非真实 AI 分析”。

实际点选通过：

1. 工作台 K 线、技术指标、评分和自动 V1 回测加载；加入自选并刷新，1/20 保留。
2. 600519：页面提交 MACD 12/26/9，区间 2025-07-05 至 2026-08-30，收益 -17.47%、14 次往返、28 笔成交（回测 #23）；切回 MA 5/20，收益 -10.46%、9 次往返、18 笔（#24）。
3. 从历史勾选 #24/#23 对照，请求区间显示 07-05 至 08-30，实际区间显示 2025-07-07 至 2026-08-28，策略参数及各自曲线正确加载。
4. #24 的“AI 解读本回测”可用；生成报告 #1，事实卡与保存结果一致。Markdown 点击后确实下载，文件内有测试模型标识、MA 参数、18/9 笔数和完整哈希。
5. 工作台默认分析生成独立报告 #2；AI 历史同时显示标准报告（评分 23）与回测解读（关联 #24），没有互相替换。

## 尚未由本轮关闭

- B 的最终 SHA 真实数据库迁移组合签字仍由 B 提交；本轮 C 数值 MySQL 验收不代签其迁移范围。
- D/A 已确认的两个非阻塞项：40007 双 toast、纯 mock 回测的旧策略名导致 AI 解读入口禁用。本轮未修改它们；真实后端新 MA 快照入口正常。
- 实时 Provider、真实 LLM、A 的完整响应式/主题页面矩阵未在本轮重新验收。
- 本地导出文件的下载事件等待曾超时，但在 Downloads 实际找到对应新文件并核验内容，因此下载结果以落地文件为准。

## 证据

`macd-replay-record.json` 是离线导出 manifest 的记录副本，包含输入包与输出哈希；体积较大的十份输出保留在本机，不在此重复提交，可用上述命令重新导出。其他日志和结果文件列于 `FILES_SHA256.json`。本地完整证据目录：`.codex-task/v3-main-prerun-20260922/`；独立运行目录：`ai-quant-platform-v3-prerun/`。
