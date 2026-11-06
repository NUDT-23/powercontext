# 浏览器端推理与量化

知识库的文本向量化全部发生在浏览器里，使用 Transformers.js 调用 bge-small-zh-v1.5。模型、分词器和 ONNX Runtime Web 的 WASM 文件都由同源静态目录提供，页面不会请求任何云端推理接口。

运行时会先探测 WebGPU。如果适配器可用，就加载 FP16 模型，用显卡加速矩阵运算；如果 WebGPU 不存在或初始化失败，则自动降级到 WASM 并加载 INT8 量化模型。顶栏会展示当前后端以及降级原因。

量化能显著压缩模型体积：FP32 约 95 MB，FP16 约 47 MB，INT8 约 24 MB。体积变小带来更快的加载和更低的带宽占用，但数值误差可能改变少量检索排序，因此需要用人工标注的 qrels 计算 Recall@K 和 nDCG@K。

多线程 WASM 需要 SharedArrayBuffer，服务端必须发送 COOP 和 COEP 响应头让页面进入跨源隔离状态；否则只能在单线程模式下运行。
