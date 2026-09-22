# C 最终入口确认：main 5fa91ea

2026-09-22，受测 main：`5fa91ea524a403b31cc5980480aeb7c25898479b`。

**结论：C 的预热入口收尾项关闭，当前无未处理的 C 算法或接口阻塞。** PR #10/#12/#14 已合并，main 的预热脚本 blob 为 `b7b46c52922cf47ef985a662f6ed7ae4ed84dc1b`，与 B a89c2ea 相同。B 已撤回基于旧 main 的“尚未合入/关闭PR14”建议；不再要求重复合入修复。

## C 本轮独立验证

在干净、分离 HEAD 的 main checkout 执行真实预热 CLI main、StockService、MarketDataService、仓储和迁移；Provider/日历为合成数据，数据库为全新内存 SQLite。三个受影响场景全部通过：

| 场景 | 结果 |
|---|---|
| 空库预热，截至日09-22、已完成日09-21 | 请求及写入裁到09-21，99行，来源正确 |
| 已完成日未知 | 退出1，Provider调用0、写入0 |
| 旧库缺09-21但含09-22异常尾行 | 补齐09-21、整段替换99行、移除09-22、来源更新 |

旧脚本 b506618 作为负向对照仍会写入100行至09-22，证明探针能识别原缺陷。本轮三个通过项的脚本和服务都来自实际 main 5fa91ea，区别于上一轮的本地组合验证。

[原始结果与Git树审计](evidence/c-warm-entry-20260922/main-5fa91ea-result.json) · [探针](evidence/c-warm-entry-20260922/warm_entry_probe.py)

```text
python warm_entry_probe.py --source <5fa91ea_CHECKOUT> --git-repo <REPO_WITH_REQUIRED_COMMITS> --candidate 5fa91ea524a403b31cc5980480aeb7c25898479b --output result.json
```

backend/frontend/tests/固定批次的 Git tree 与已验收 bcbd559 完全相同；运行代码差异仅 `scripts/warm_market_data.py`。因此本轮按差异复验入口，不重复557项/固定九组/MySQL迁移。原固定九组与MySQL证据仍绑定原受测基线及相同树/输入范围，不冒记为本轮重新执行。结果JSON中整棵scripts树相等为false正是这项修复差异，不是测试失败。

未调用真实行情或LLM，未修改现有数据库；本轮SQLite结论不能冒记成新增MySQL、实时或浏览器验收。D记录的用户最终验收、用户代理A页面门禁保留其执行范围。

## PR #16：仅新增测试，不是修复前置条件

C 独立获取 `19c9276ae05114ae33c8bd57f9eedb01de77fb38`；相对main 5fa91ea仅新增 `tests/test_warm_entry_boundary.py`（157行）。在该精确checkout执行该文件：**3 passed in 1.83s**。无生产代码变化，未重跑B所述560全量；560及旧脚本2失败/1通过为B独立记录，不列为C实测。

建议D保留有价值的入口接线守卫，是否合并由D决定，不作为C本轮关闭前置条件。第2条实际为 `inspect.getsource` 检查预热脚本两段源码字符串，未执行请求依赖，也未直接比较API入口；“与请求路径逐字相同”不能解释为动态一致性证明。后续可改成行为断言以降低无害重构造成的误报，此为非阻塞维护建议，C不改B测试。

## 发布记录边界

本轮证据推送C既定分支。PR #12已经以5aa24aa关闭合并，之后C分支提交不自动进入main。D如需收录最终确认文档，应明确同步后续C文档；这不重开已关闭的算法/接口事项。PR #13是D交给A的后续视觉范围，不属于本轮C待办。
