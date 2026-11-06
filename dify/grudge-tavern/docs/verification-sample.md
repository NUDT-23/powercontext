# 验证样例 · 跨会话记忆

本文件给出可直接照做的两段会话，以及每一段预期发生的事，用于人工复核。

> 自动验证：`python scripts/04_verify.py`
> 自动追踪：`python scripts/05_collect_trace.py`

---

## 前置条件

- Dify 与 PowerContext 已按 README 第 4 节启动；
- `scripts/01_create_scope.py` 已创建 scope（建议加 `--seed` 写入两条种子旧闻）；
- DSL 已导入、发布，模型可用。

手动体验时，请确保两段会话是**两个不同的 Dify 会话**（新开一个聊天，或使用不同的
`conversation_id`）。

---

## 第一段：留下新账

**输入**

```
我是头一回来。先赊一壶你们最贵的招牌酒，记十二个银币在我账上。还有，我刚才手滑把莉拉的琴弦弄断了一根，你可别说是我干的。
```

**预期**

- 格罗姆 / 莉拉 / 老K 中 1–2 人回应，语气符合人设；
- 至少一人提到"十二银币""赊账""琴弦"之一；
- 回复末尾有状态脚注（`> 格罗姆：……`）；
- 工作流执行记录中顺序为：
  `prepare_memory → list_memories → merge_memory → narrate → parse_reply → decide → remember → answer`；
- PowerContext 中新增一条形如：

  ```
  酒馆记忆｜玩家：酒馆来客｜涉及：格罗姆、莉拉｜在场：格罗姆、莉拉、老K｜详情：……
  ```

核对方式：

```bash
curl -s http://127.0.0.1:8010/v1/atomic-memory/list \
  -H 'Content-Type: application/json' \
  -d '{"scope_id":"<scope_id>","limit":20}'
```

---

## 第二段：换个会话翻旧账

**输入**

```
还认得我吗？说说看，我上次欠了多少银币，又弄坏了谁的琴弦？
```

**预期**

- 这是一个全新的 `conversation_id`，Dify 侧没有上一轮历史；
- NPC 仍能说出"十二银币"和"莉拉的琴弦"（或等价表述）；
- 至少命中两个关键词：`12` / `十二` / `琴` / `莉拉`；
- `context/prepare` 的返回可能为空（短问句），但 `atomic-memory/list` 已兜底；
- 工作流中 `prepare_memory` 与 `list_memories` 在 `narrate` 之前执行。

---

## 自动断言的判定标准

`04_verify.py` 会：

1. 分别发送两段会话（会话 id 均为空，由 Dify 新建）；
2. 断言两段回复非空；
3. 断言两次 `conversation_id` 不同；
4. 断言第一段之后 PowerContext 新增了记忆；
5. 断言第二段回复命中至少 2 个关键词；
6. 把脱敏后的请求、回复、memory list、prepare 返回写入 `evidence/`。

失败时会打印第二段完整回答，便于判断是模型演出问题还是记忆链路问题。

---

## 常见误判

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 第二段完全失忆 | scope id 不一致 / 未替换占位符 | 重跑 `02_render_dsl.py` 并重新导入 |
| 第一段没有写入 | LLM 未输出合法 JSON 或 `memorable=no` | 查看 workflow run 的 `parse_reply` 输出 |
| prepare 一直为空 | 查询过短或缺少锚点 | 这是预期，list 兜底生效 |
| 回复没有细节 | 模型未遵守 prompt | 换模型或降低 temperature 后重试 |
