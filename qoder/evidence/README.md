# 验收证据包

本目录用于存放「Qoder × OceanBase」赛题的验证材料。除说明文件外，大文件（录屏、截图、问卷原始导出）默认被 `.gitignore` 忽略，提交前请按平台要求单独上传或放入私有仓库的 release/附件。

## 目录

| 目录 | 内容 | 生成方式 |
| --- | --- | --- |
| `qoder/` | Qoder 对话截图、录屏、账号 UID、commit 对照表 | 手动整理 |
| `powercontext/` | 记忆读写 trace、Dashboard 截图、记忆开关对比 | `make evidence` + 手动截图 |
| `seekdb/` | 混合检索 trace、seed 统计、查询样例 | `make evidence` |
| `usage/` | 真实用户事件、反馈 CSV、问卷与提效对比 | `make evidence` + 手动补充 |
| `demo/` | 产品截图（`ui-*.png`，无头浏览器自动截取）、演示视频 | `export_evidence` 收集截图；视频手动录制 |
| `verification/` | 自动验收报告与样例数据 | `make verify` |

## 提交前检查

- [ ] `make verify` 全部 PASS
- [ ] `make evidence` 生成 manifest.json
- [ ] Qoder UID、对话截图、commit hash 对应
- [ ] PowerContext 记忆写入/召回 trace 含时间、scope、artifact
- [ ] seekdb 检索 trace 含 query、过滤条件、结果 id、耗时
- [ ] 至少 10 名真实用户的事件与问卷
- [ ] 3 分钟演示视频，无断点
- [ ] Qoder Sites 公开链接无痕窗口可访问
- [ ] 仓库不含任何真实密钥
