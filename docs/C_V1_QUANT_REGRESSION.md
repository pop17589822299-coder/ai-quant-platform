# C：V1 量化一致性回归与 R2 冻结交接

更新时间：2026-09-11。**B 的 R2 包已实际下载，交付格式及 C 限定范围的一致性回归通过；V1 全链路仍未验收。**

本次 C 调整的是交付清单、校验入口和说明，不修改量化公式、参数或 API 字段。A/D 所需的 MySQL 回读、元数据和完整默认策略参数已在同一 R2 包内，**不需要 C 重新生成、转换或另发一份数据**。

## 版本和修改边界

- D 内含的 B 算法/服务基线：`35a048271d437281ed837ac94b437aac5302f332`。
- B PR #7 固定交付：`7157cf6abcdfba010bbbb164a460ccd9463e837f`，Release `v1-frozen-package-r2`。已核对其整个 `backend` Git tree 与 `35a0482` 相同，均为 `5372882b7b0ad8d0691c41e77266009d2aba4199`；新增的是打包、诊断及相应测试，不是数据/量化服务逻辑变化。
- D PR #8 装配基线：`a097f9a58c457d0fe194a038d8ad1d49ef044337`，保持草稿。
- C 工作分支：`feature/V1-ai-quant-regression`，从上述 D 提交开始。
- C 既有 R2 回归提交：`f02c8e0a1f13fddd9924a63c22f3ff2aea521491`；本次在同一分支补充交付校验。
- C 只维护独立验证脚本、测试、交付 JSON 清单和本说明。不修改 `backend/app/quant`、B 数据/缓存模块、D 路由/AI 服务、A 前端或共享 API 契约。
- 此分支包含 D 的尚未合并代码；审查 C 的增量时与上述 D SHA 比较，**不要直接把整条分支合并到 main**。

PR #8 的变化是请求级依赖注入及统一数据入口，不是量化公式变化。D 的 K 线及量化服务均经 `MarketDataService.query_daily` 获取规范化数据。

历史问题 `4325704` 的键名与 D 不一致、缺少顶层元数据及可下载包，已在 R2 修正并复验关闭，不再作为当前阻塞。已验收 R2 原文件保持字节不变；B 如有修改，应给出新版本、新 SHA 和差异后再针对性回归，不覆盖 R2。

## 给 A/D 的同一份交付

下载 [R2 Release](https://github.com/Lawera2601/ai-quant-platform/releases/tag/v1-frozen-package-r2) 中的 [完整 ZIP](https://github.com/Lawera2601/ai-quant-platform/releases/download/v1-frozen-package-r2/ai-quant-v1-frozen-package-r2.zip)，保留压缩包并解压。`--frozen-dir` 应指向直接包含 `metadata.json` 的目录，而不是压缩包所在的上一层目录。

| A/D 需要的内容 | R2 中的位置/口径 |
|---|---|
| MySQL 回读 | `mysql_readback_600519.json`，403 条；B 交付的实际导出，C 校验字节并独立重算 |
| 403 条 qfq 日线 | `600519_qfq_20250101_20260831.json`，实际覆盖 2025-01-02 至 2026-08-31 |
| 真实冻结交易日历 | `a_share_trade_dates.json`，8797 个日期；上述窗口内日期集合为 403 个 |
| 股票基本信息 | `stock_basic_600519.json`，附 `.raw.json` 和 `.provenance.json` 采集证据 |
| 元数据及完整默认策略参数 | `metadata.json` 的来源/窗口/精度字段、`quant_config` 全量对象及 `quant_expectations` 五项 |
| B 原始清单 | `MANIFEST.json`；保持原文件，不补写或重算覆盖 |
| C 完整校验清单 | 本仓库 `docs/C_FROZEN_R2_HANDOFF.json`：下载前缀 + ZIP/8 个 JSON 文件名、字节数、完整 SHA-256、B/D SHA、默认参数及预期；校验报告输出各文件完整下载 URL |

C 清单是独立交付索引，不替代或修改 B 的 `metadata.json`、`MANIFEST.json`。原 MANIFEST 列出 6 个文件，C 清单额外覆盖 provenance、MANIFEST 本身及 ZIP，避免只校验部分文件。C 清单不是 D runner 的 metadata 输入；D 仍读取 R2 包内的原始 `metadata.json`。

单独下载入口：[MySQL 回读](https://github.com/Lawera2601/ai-quant-platform/releases/download/v1-frozen-package-r2/mysql_readback_600519.json)、[metadata](https://github.com/Lawera2601/ai-quant-platform/releases/download/v1-frozen-package-r2/metadata.json)、[原始 MANIFEST](https://github.com/Lawera2601/ai-quant-platform/releases/download/v1-frozen-package-r2/MANIFEST.json)。完整回归仍需要整包，不是只拿回读文件即可运行。

来源时间须分别保留：

- 行情抓取结束：`2026-09-09T02:05:50.619248+00:00`，最后交易日为 2026-08-31；不得替换为组包或验收时间。
- 日历抓取结束：`2026-09-09T02:07:13.303479+00:00`。
- 股票快照抓取：`2026-09-10T08:12:51.855484+00:00`，来源 `push2delay.eastmoney.com`。原始响应与快照代码/名称/行业/市值逐字段一致；C 没有在本次离线验收中重新访问该端点。
- `news=null`，`news_status` 明确为 absent。包里没有真实新闻快照，不能生成替代新闻，也不能将缺失解释为“已验证当天没有新闻”。

前端及报告应显示“冻结数据联调”和样本日期，不能把不同日期的冻结快照包装成同一时刻的实时行情。

## 验证实现

`scripts/verify_quant_handoff.py` 只读核对固定 R2 交付：全部 8 个 JSON 的字节数/哈希、MANIFEST 与 metadata 对应关系、完整默认参数和包结构；传入 `--archive` 时额外校验原始 ZIP。复用 D 真实 `load_package`，不运行量化/SQLite 回归，不创建、修改或迁移数据库，也不调用真实行情或 LLM。未提供 ZIP 时只说明解压文件已校验，不宣称本次校验过 ZIP。

`scripts/validate_quant_consistency.py` 是 C 的完整离线回归入口；R2 推荐加 `--verify-r2-handoff`，先执行交付门禁，再执行以下检查：

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

## R2 实际材料与完整量化结果

使用已实际下载的 R2 原始文件。没有重新抓取或生成替代真实数据。完整 9 资产清单见 `docs/C_FROZEN_R2_HANDOFF.json`，下列三项是其中的量化输入：

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

报告将 `sqlite_service_and_http_regression` 和 `b_export_comparison` 分开标记，`connected_to_mysql=false`，并保留完整参数、输入哈希、脚本哈希、实际运行版本、未执行项及完整直接计算 JSON。

## 可复现命令

以下均在仓库根目录运行。PR #8 的验收脚本使用 Python 3.10+ 语法，C 使用独立 `.venv` 的 Python 3.12.10。首次用系统默认 Python 3.9 收集测试失败，未据此修改 D 脚本。

只验证 R2 交付及原始 ZIP：

```powershell
.\.venv\Scripts\python.exe scripts/verify_quant_handoff.py `
  --frozen-dir frozen/release-r2-7157cf6/package `
  --archive frozen/release-r2-7157cf6/ai-quant-v1-frozen-package-r2.zip
```

R2 交付门禁与完整量化回归一起执行：

```powershell
.\.venv\Scripts\python.exe scripts/validate_quant_consistency.py `
  --frozen-dir frozen/release-r2-7157cf6/package `
  --verify-r2-handoff `
  --archive frozen/release-r2-7157cf6/ai-quant-v1-frozen-package-r2.zip `
  --output-dir frozen/release-r2-7157cf6/c-handoff-20260911

.\.venv\Scripts\python.exe -m pytest tests -q
```

R2 模式不接受通过 `--metadata` 替换原始 `metadata.json`；主回归入口的 `--archive` 必须与 `--verify-r2-handoff` 一起使用。相对路径只是解压后的示例布局，不是其他成员必须使用的本机绝对路径。

重复执行完整回归应使用新的 `--output-dir`，脚本不覆盖旧结果。报告与完整直接计算 JSON 放在该输出目录，保留实际代码/脚本/输入哈希、完整参数、运行环境与未执行项；大体积原始文件、私人路径和运行输出不提交 Git。

既有不带 `--verify-r2-handoff` 的完整包模式和 `--source-dir` 旧量化材料模式仍可使用；后者不代表 D 完整冻结包已验收。完整包模式先调用 D 的真实 `load_package`，不是重写另一份 D 契约。metadata 必须明确 qfq 和 daily（daily 也可由完整 `quant_config.frequency` 给出）。没有真实股票快照时不得手写替代。上述 C 入口均不会连接真实 MySQL 或 LLM。

失败时非零退出，并报告第一处不同的路径，例如 `d_http_cached.backtests.response.data.equity_curve[1].equity`。先看行情字段/参数/Provider 调用次数，区分数据转换、参数或缓存问题，再判断是否属于量化算法；不通过额外舍入修改 C 算法来掩盖差异。

## 本轮执行结果（2026-09-11）

以下首轮结果来自 `f02c8e0` 后的 C 本地修改工作树，执行当时尚未提交/推送；机器报告如实保留 `working_tree_status` 和每个校验脚本/清单的 SHA，不把旧 HEAD 当成本轮代码已提交的证据。发布时的实际新 SHA、远端核验和干净提交复跑结果以 PR #8 的 C 最新交接评论为准，不用此历史快照推断当前发布状态。

- 已现场核对 GitHub PR #7/#8 的远端 SHA 仍分别为 `7157cf6`、`a097f9a`，Release 的 9 个 asset digest 与本地原包一致；B `35a0482` 与 `7157cf6` 的 backend tree 相同。
- 只读交付校验：`PASS_DELIVERY_ONLY`，9 个资产（8 JSON + 原 ZIP），D `load_package=PASS`。没有以“预期结果”冒充此步骤已经重新计算的结果。
- 上节带 R2 门禁的完整回归命令：`PASS_SCOPED`、`bundle_complete=true`。完整指标、预热 null、评分/原因、24 条订单、回测与三类曲线严格一致；B 导出与直接计算一致，SQLite 首次/缓存/HTTP/两种缺行恢复均通过。
- `python -m pytest tests -q`：**367 passed**、1 warning，19.52 秒（同一 `.venv`）。其中本轮新增交付校验测试 35 项；原 332 项全部通过。
- `python -m pytest tests/test_verify_quant_handoff.py tests/test_validate_quant_consistency.py tests/test_quant_consistency_regression.py -q`：**145 passed**、1 warning，8.89 秒。这是 C 专项子集，不与全量数相加。
- 新测试覆盖全部 9 资产被修改、缺失文件、数据和下载清单一起被改仍无法绕过本地固定哈希、默认参数漂移、CLI 非零退出和兼容边界；小型单元夹具明确为 synthetic，不冒充真实数据。
- 机器报告：`frozen/release-r2-7157cf6/c-handoff-20260911/quant_consistency_report.json`；同目录完整结果 `quant_direct_analysis.json` 的 SHA-256 仍为 `9aed066204ba0689470ddb809e96219c69492cd0695c589f4b0610d79a3adafb`，与上一轮完全相同。
- 该次回归未新连 MySQL，未执行真实 LLM/浏览器/实时 AKShare；只读核验及回归未改变 R2 原文件。没有修改 A/B/D 业务模块，没有合并 main；该次回归结束时尚未发布交接评论。

2026-09-11 提交前再次执行：全量 **367 passed**（15.81 秒）、独立 C 专项 **145 passed**（7.80 秒），均只有同一条依赖弃用 warning；compileall、`git diff --check` 及五文件提交范围审查通过。B/D 远端仍为上述固定 SHA，R2 的 9 个 Release asset digest 未变。提交后用同一命令和新的输出目录再次生成报告，以实际提交 SHA 标识发布证据。

## 已有 R2 实测证据（2026-09-10）

以下是 C `f02c8e0` 的已完成记录，不把此前数量冒充本次新增校验后的测试数量：

- ZIP 实际为 52816 字节，SHA-256：`90b1f207b209cfea3a1570abb3c2fbbda5afb7079e01e3c11a34671e8c1df7dd`。ZIP 与 8 个 JSON 均与 Release asset digest 一致。
- D 真实 `load_package` 通过；`compare_package_quant` 返回 `data_equal=True`、`analysis_equal=True`。
- C 完整包模式：`PASS_SCOPED`、`bundle_complete=True`、`connected_to_mysql=False`。
- D+C 全量：332 passed、1 warning，14.47 秒；其中既有 C 专项为 110 项。B `7157cf6` 独立工作树：157 passed、1 warning，8.82 秒。两套数量不能相加充当一套全量结果。
- warning 为 Starlette/AnyIO 依赖弃用提示，无测试失败。
- 环境：Python 3.12.10、pandas 2.3.3、NumPy 2.5.3、SQLAlchemy 2.0.52、FastAPI 0.115.14、Pydantic 2.13.5；未修改团队 requirements。
- 机器报告在忽略目录 `frozen/release-r2-7157cf6/c-full-regression/quant_consistency_report.json`。同目录完整结果 `quant_direct_analysis.json` 的 SHA-256 为 `9aed066204ba0689470ddb809e96219c69492cd0695c589f4b0610d79a3adafb`，与此前 C 完整结果相同。

## 仍待联合验收

1. **C 交付工作**：提供固定 R2 的下载/校验索引、参数和独立完整量化结果。现有契约不要求改 C 算法；只有新数据或代码版本到来后再做相应回归。
2. **B/D 新的真实 MySQL 验收**：在明确隔离的测试库验证首次查询、缓存、回读及中间缺行恢复。C 的 SQLite 回归和收到的 B 既有 MySQL 导出重算不替代该环境验收；**C 本轮不连接 MySQL**。
3. **D/A 冻结全链路**：真实 LLM → 正式 AI 路由 `code=0` → `ai_analysis` 成功新增及全部报告字段一致 → A 浏览器关闭全部 Mock 展示。冻结新闻快照缺失，本轮不能据此宣称真实新闻已验收。
4. **实时 AKShare 链路单独记录**：据 B 最近同步，搜索/股票信息/日线实时数据源失败并映射 `50001`，新闻和日历曾实测通过；这不是 C 本轮实时复测结论。A 可验证错误态展示，但 `50001` 不能算搜索、详情或量化正常业务链路通过。网络恢复后仍须逐接口重跑成功路径，不直接推断代码与链路全部正常。
5. C 的限定范围 PASS 不解除 D 草稿，不代表主分支合并批准。维持团队约定的合并顺序，联合证据齐全前不合并 main。

离线单元测试夹具明确为 synthetic，不用于证明真实 qfq、真实交易日历、真实 MySQL 或实时源成功。真实冻结一致性结论来自已校验的 R2 原文件，分开记录。
