# 智谱 GLM-5.3-Flash API 实测笔记

模型 `glm-5.3-flash`，base_url `https://open.bigmodel.cn/api/paas/v4`，OpenAI 兼容。
原生多模态（图片输入）、1M 上下文、支持 JSON Output。以下全部实测验证（2026-08）。

## 关键差异 vs DeepSeek 版（本移植的三处架构改动）

1. **思考无法关闭**：`thinking={"type":"disabled"}` 返回 400（"该模型始终思考，
   不支持关闭思考；请使用 low、high 或 max"）。
   替代方案：`extra_body={"reasoning_effort": "low"}`，实测 reasoning_tokens=0
   ——批量/结构化任务用它等价于 DeepSeek 的关思考；深读回答用 "high"/"max"。
2. **无 Files API**：图片一律 base64 data URL 内联传（实测单请求 30 图正常）。
   原版的上传断点续传/file_id 失效重传机制整体移除。
3. **图片按分辨率计费**：约 750 像素²/token（500×500≈346 tok、1000×1000≈1318 tok、
   900×1273 页图≈1500 tok）。DeepSeek 单图封顶 384，GLM 不封顶 →
   PDF 渲染 dpi 默认从 150 降到 **110** 控制成本。

## 与 DeepSeek 相同的坑

- **reasoning 计入 max_tokens**：预算不足返回空 content + finish=length（实测
  max_tokens=64 必现）。所有调用给足预算，客户端重试空 content。
- JSON Output：`response_format={"type":"json_object"}` 可用；解析仍需宽容处理。
- 官方推荐 `temperature=1, top_p=0.95`；结构化抽取配合 effort=low 输出稳定。

## 调用参数基线（glm_client.py 已封装）

| 场景 | effort | max_tokens |
|---|---|---|
| 批量页/帧索引、精排、镜头卡 | low | 8192~16384 |
| PDF/视频深读回答 | high | 24576 |
| 复刻提示词生成 | high | 32768 |

密钥：环境变量 `GLM_API_KEY`（或 `ZHIPU_API_KEY`）> `~/.glm_api_key` 首行；代码不内置。
