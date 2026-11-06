# BookVault 搜索规格

本规格是 `bookvault.search.search_books` 的唯一行为依据。实现必须逐条满足 R1-R6，并保持 C1-C3 兼容。

## R1 查询过滤

`search_books` 按 `query` 对图书的 `title` 和 `author` 做不区分大小写的子串匹配；`query` 为空时不做查询过滤。

## R2 多标签 AND 过滤

`tags` 参数用于筛选图书。多个标签之间采用 AND 语义：图书必须同时包含所有有效标签才算匹配。

## R3 空白标签忽略

每个标签先去除两端空白；去除后为空的标签不参与匹配。`tags` 为 `None` 或空列表时不启用标签过滤。

## R4 标签大小写不敏感

标签匹配不区分大小写，例如 `PROGRAMMING` 与 `programming` 等价。

## R5 limit 边界校验

`limit` 必须是 1 到 100（含）之间的整数。`limit` 小于 1 或大于 100 时必须抛出 `ValueError`。

## R6 结果排序

过滤完成后按 `rating` 降序、`id` 升序排列，再按 `limit` 截断。
