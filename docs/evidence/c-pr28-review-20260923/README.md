# C 对 B 的 PR28 与演示风险清单复核

被测 PR：27ye/ai-quant-platform#28。
Head：f4740d6de8f77af2c86037bf2c5c87f83706a5c1。
Base：83bcbd118126db4fa99003e1809865637e621e5b。
日期：2026-09-23。

## PR28 结论

未发现阻塞该最小修复的问题，可批准进入 D 的合并流程。本轮未合并、未改生产文件，也未替换正在演示的服务。

- 定向测试：`pytest tests/test_stock_catalog.py tests/test_catalog_sync_endpoint.py tests/test_provider_retry.py -q`，41 passed。
- SQLite 和独立真实 MySQL：base 遇到已有代码改名时复现 DatabaseOperationError；同一批中的新增行回滚。head 能同时新增、改名和保留未变化名称，重复提交幂等，新会话回读及名称搜索正确。
- base 上名称完全未变的已有目录重复刷新也成功。因此 PR 描述和代码注释中的“任何已有目录/每次刷新必失败”应改为“已有代码名称发生变化时失败”；不阻塞功能修复。
- compileall、git diff --check 通过；相对base，quant/API/schema/migrations均无变化。
- 未重复全量测试；不将 B 的758项结果计作 C 执行结果。MySQL使用小规模明确测试记录，未重抓全市场目录、未碰正式ai_quant或演示库。

## 风险清单修正

来源：Issue20 comment5788170331。

1. “串行演示不受影响”不成立。C此前probe_stability.py的调用者按股票/接口串行执行，仍出现过 too many in-flight AKShare calls。生产代码对超时线程仅停止等待，不取消线程；全类活动计数直到后台函数退出才递减。前几个串行请求超时后仍可能在后台并发存活，最终触发4线程上限。
2. 本轮在独立进程做受控复现：连续串行调用5次，前4次通过Event模拟未结束任务、各等待0.03秒超时，第5次被上限拒绝；finally释放事件并确认活动计数归零。这是机制测试，不是新的真实供应商故障，也没有占用运行中后端线程。保护能限制资源增长，但不能保证后续串行取数可用；“重试即可”也不应当作必然恢复。
3. 新浪分页配置是fallback_timeout_seconds=3、tencent_retry_attempts=2，传输异常在尝试耗尽后失败，不能概括为“一次超时即中止”。非200当前立即抛出，属于不同路径。C此前真实59.69秒同步计数为5566，并非5567。
4. “按IP拒绝/服务本身健康”属于对网络对照的推断，未获供应商确认；第三方代理返回成功也不能完全排除出口、代理缓存或路由差异。建议写“观察到不同出口可达性差异，疑似限流/访问策略”。本轮未重做 B 的各出口实验，不能把其来源证据升级为 C 独立验证。

## 其他分工

Issue15是否关闭由D决定；storable_strategy_version注释是可选清理，不属于本次C算法修复。PR28合入最终main后的写库闭环属于后续集成验收，本轮只签上述head。未启动B提出的5173/8000环境，以免与用户当前演示环境混淆。

本机证据：C:/Users/15149/Desktop/qproject/.codex-task/c-pr28-review-20260923/。
