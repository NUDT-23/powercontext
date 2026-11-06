# seekdb 快速体验

seekdb 是 OceanBase 推出的轻量级向量数据库。它可以在 Node 进程内以嵌入式方式打开本地数据目录，不需要单独启动数据库服务。

创建集合时需要给出 Schema：向量索引使用 HNSW，距离度量为余弦；全文索引使用 ik 分析器。写入文档后调用 refresh_index，让新数据立刻参与检索。

混合检索通过 hybridSearch 完成。一次调用同时执行向量通道和全文通道，并由数据库使用 RRF 融合排序。应用层不再拼接两份结果，避免重复排序和分数不可比的问题。

如果需要在 Windows 上体验，由于原生绑定在部分环境存在兼容问题，可以使用 Docker 运行 Linux 版本，并通过 LD_PRELOAD 加载 libseekdb.so。
