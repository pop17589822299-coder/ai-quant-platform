# C：PR #8 量化一致性回归与交接

更新时间：2026-09-10。结论是 **C 的限定范围回归通过，V1 全链路仍未验收**。

## 版本和修改边界

- D 内含的 B 算法/服务基线：`35a048271d437281ed837ac94b437aac5302f332`。
- 本次交付前另核对 B 最新 PR #7：`4325704a8f868ad2653b1ada633349f1abf88bdd`，仅新增数据源诊断文档和打包脚本；`backend` 与 `tests` Git tree 均与 `35a0482` 完全相同。下述 332 项是 D+C 工作树实测数量，不冒称最新 B 分支单独运行的数量。
- D PR #8：`a097f9a58c457d0fe194a038d8ad1d49ef044337`，保持草稿。
- C 工作分支：`feature/V1-ai-quant-regression`，从上述 D 提交开始。
- 本次仅新增 C 验证脚本、自动化测试、本说明。不修改 `backend/app/quant`、B 数据/缓存模块、D 路由/AI 服务、A 前端或共享 API 契约。
- 此分支包含 D 的尚未合并代码；审查 C 的增量时与上述 D SHA 比较，**不要直接把整条分支合并到 main**。

PR #8 的变化是请求级依赖注入及统一数据入口，不是量化公式变化。D 的 K 线及量化服务均经 `MarketDataService.query_daily` 获取规范化数据。

## 验证实现

`scripts/validate_quant_consistency.py` 是 C 的离线入口：

1. 在任何服务执行前检查文件 SHA-256；严格解析 JSON，拒绝重复键、NaN、Infinity、溢出数值。
2. 检查 403 条行情的原始字段、数值类型、日期唯一升序、OHLC 合法、整数非负 volume、日历日期集合一致以及元数据。
3. 入库前原始数据按已约定的价格 4 位、amount 2 位、换手/涨跌 6 位构造独立基准。**不调用 B 的舍入函数充当独立基准，不对收到的 MySQL 回读文件再次舍入、补行或排序以掩盖差异。**
4. 同一默认 `QuantConfig` 下用原有 `analyze_quant_dataframe` 比较整个结果，包括 meta/参数、latest、全量指标与预热 null、评分/原因、全部订单、回测指标、权益/基准/回撤曲线。
5. 调用 `scripts/quant_consistency_regression.py`：使用独立内存 SQLite、真实 B Service/Repository 和 D `create_app()`。只替换数据库会话、外部行情 Provider 和交易日历三个边界，不替换量化服务或算法。
6. 逐条完整比较四个 HTTP 响应，并以 Provider 调用次数证明首次查询、缓存命中和缺行后的重拉。

HTTP 比较映射：

| D 接口 | C 期望结果 |
|---|---|
| `GET /api/v1/stocks/600519/kline` | 同一规范化行情的全部字段 |
| `GET /api/v1/stocks/600519/indicators` | `analysis.series.indicators`，含预热 null |
| `GET /api/v1/stocks/600519/score` | `analysis.score` 全字段 |
| `POST /api/v1/backtests` | `analysis.backtest` 全字段，加接口已有的 `stock_code` |

请求均显式指定同一 `start_date/end_date`。不把不同日期窗口、不同参数或原始高精度数据与规范化数据混为一谈。

## 本轮实际材料与结果

使用此前已经交付的真实冻结行情、日历和 B 的 MySQL 导出文件。没有重新抓取或生成替代真实数据。

| 文件 | SHA-256 |
|---|---|
| `600519_qfq_20250101_20260831.json` | `fe6622237a6e5c764918b89fc33397e7a6ed25743f175603ef626cc4840d22a2` |
| `a_share_trade_dates.json` | `20ea7c1986245e0e6cdf71f648cd95bfc07c552c7fb844467c5fc4b57267271e` |
| `mysql_readback_600519.json` | `5e92659b05647ca17c52ddb0d1a86cf952d46500ce26f2abb342cf693b4082df` |

- 实际行情区间：2025-01-02 至 2026-08-31，403 行；冻结真实日历对应日期集合也是 403 天。
- qfq/daily 依据原始抓取元数据；不能仅凭 OHLC 数值反推复权方式。原始行情抓取结束时间为 `2026-09-09T02:05:50.619248+00:00`，不是本次回归时间。
- 统一精度后的直接输入与收到的 B 回读数据逐字段完全相等，完整量化输出严格相等，不设置浮点容差。
- SQLite 首次查询、实际缓存命中、Repository 回读及 D 四个接口均严格一致。
- 连续删除中间 2 条后剩 401 行；分散删除 3 条后剩 400 行。两次均保持首尾日期、最大间隔 11 天（小于 15），仍能检测缺失并恢复 403 行。因此此次通过不是仅靠首尾/行数下限/最大间隔判断。
- Provider 累计调用：首次 `1` → 缓存及四接口仍 `1` → 连续缺行恢复 `2` → 分散缺行恢复 `3`。恢复后再次查询不重复拉取。

关键输出（订单数不同于已完成交易对数）：

| 项目 | 结果 |
|---|---:|
| 评分 | 33 |
| 订单数 `order_count` | 24 |
| 完成交易对数 `trade_count` | 12 |
| 指标/权益/基准/回撤序列 | 各 403 点 |
| `total_return` | -0.09165774117956027 |
| `final_equity` | 90834.22588204397 |
| `max_drawdown` | -0.24473361547016392 |
| `sharpe_ratio` | -0.3336222348975976 |

预热 null 数：MA5/10/20/60 分别为 4/9/19/59；RSI14 为 14；BOLL 三条轨道各 19。比较的是每个位置的实际值，不只是这些数量。

报告将 `sqlite_service_regression` 和 `b_export_comparison` 分开标记，`connected_to_mysql=false`，并保留完整参数、输入哈希、脚本哈希、实际运行版本、未执行项及完整直接计算 JSON。

## 可复现命令

以下均在仓库根目录运行。PR #8 的验收脚本使用 Python 3.10+ 语法，本轮使用独立 `.venv` 的 Python 3.12.10。首次用系统默认 Python 3.9 收集测试失败，未据此修改 D 脚本。

实际执行记录：

- D 原始测试（排除本次两个新测试文件）：222 passed。
- 当前全量：332 passed（14.51 秒），其中 C 新增专项 110 passed（单独执行 5.87 秒）。
- 存在 1 条 Starlette/AnyIO 依赖弃用提示，无测试失败。
- 两个新增脚本及两个测试文件的 compileall 通过。
- 环境：Python 3.12.10、pandas 2.3.3、NumPy 2.5.3、SQLAlchemy 2.0.52、FastAPI 0.115.14、Pydantic 2.13.5。依赖安装在本分支独立 `.venv`，未修改团队 requirements。
- 提交后的机器报告在 Git 忽略的 `frozen/c-v1-regression/published/quant_consistency_report.json`，完整计算结果在同目录 `quant_direct_analysis.json`。报告记录实际 CLI 参数、源文件与脚本哈希、代码 SHA，不提交私人本机数据路径及大体积行情文件；此前 `final/` 是提交前快照。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest tests/test_quant_consistency_regression.py tests/test_validate_quant_consistency.py -q
```

旧量化材料 + B 实际导出的量化专项模式（不冒充 D 完整冻结包）：

```powershell
.\.venv\Scripts\python.exe scripts/validate_quant_consistency.py `
  --source-dir frozen/quant_source `
  --readback frozen/mysql_readback_600519.json `
  --readback-sha256 5e92659b05647ca17c52ddb0d1a86cf952d46500ce26f2abb342cf693b4082df `
  --output-dir frozen/c-regression-run
```

上面的目录为交付后可采用的相对目录，不表示新数据包已经到齐。旧 `metadata.json` 应与其引用的原始行情、日历一起放在 source-dir；重复运行需使用新的 output-dir，脚本不覆盖旧结果。

收到 B/D **完整**包后：

```powershell
.\.venv\Scripts\python.exe scripts/validate_quant_consistency.py `
  --frozen-dir frozen/v1-package `
  --output-dir frozen/c-full-package-run
```

完整包模式先调用 D 的 `load_package` 校验股票快照、统一 metadata、四个文件的哈希、完整默认参数及预期结果；metadata 必须明确 qfq 和 daily（daily 也可由其完整 quant_config.frequency 给出）。没有真实股票快照时不得手写替代。此模式仍仅运行离线 C/SQLite/HTTP 回归，**不会连接真实 MySQL 或 LLM**。

失败时非零退出，并报告第一处不同的路径，例如 `d_http_cached.backtests.response.data.equity_curve[1].equity`。先看行情字段/参数/Provider 调用次数，区分数据转换、参数或缓存问题，再判断是否属于量化算法；不通过额外舍入修改 C 算法来掩盖差异。

## 仍待联合验收

本次检查新增阻塞：B `4325704` 的 `scripts/build_frozen_package.py` 输出 `stock_basic/expected_results`，而 D 的 `load_package` 需要 `stock/quant_expectations`，另缺顶层 `stock_code/actual_start_date/actual_end_date/captured_at/rows`。以 B 实际 metadata 键名做纯结构离线复现时，D 在读取文件前即报 `frozen metadata is missing required fields`。该复现不是使用真实新包，也不生成股票数据。

请 B 按 D 已提交的契约修正打包格式；从原始元数据保留实际抓取时间和日线窗口，先核对原始文件哈希，再组包。`quant_expectations` 应仅包含 score=33、order_count=24、equity_curve_points=403、total_return=-0.09165774117956027、final_equity=90834.22588204397，其他说明放在对象外。股票快照需保留真实来源及实际抓取证据，不能由 C 补造。未在最新公开 PR 评论及 Releases 中找到实际包下载位置；提交 builder 不等于交付样本。

1. B 交付新的完整冻结包、统一 metadata、真实股票信息快照及新 SHA 后，再用完整包模式复核。旧文件不能被宣称为新包。
2. B/D 在新的明确隔离 MySQL 环境执行首次查询、缓存、回读及缺行恢复，C 再核对同一数据与完整量化结果。本轮只是独立验证了 B 已交付的 MySQL 导出，**C 未在本轮连接 MySQL**。
3. D 的真实 LLM、正式 AI 路由、`ai_analysis` 成功新增及字段一致，A 的关闭 Mock 浏览器展示，以及实时 AKShare 冒烟仍需分别验收。
4. C 的这次 PASS 不解除 D 草稿、不代表合并批准。本次只提交并推送 C 的独立回归分支供审查，不合并 main，不修改 B/D 的远端分支。

离线单元测试夹具明确为 synthetic，不以它证明真实 qfq、真实交易日历、MySQL 或实时源成功。真实冻结回归结果来自上面三个文件，单独记录。
