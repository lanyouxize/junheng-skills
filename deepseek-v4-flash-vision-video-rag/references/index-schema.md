# 视频索引结构与提示词

## index.json（.cache/<视频sha256前16位>/index.json）

```jsonc
{
  "video": "绝对路径",
  "video_name": "xxx.mp4",
  "sha256": "内容哈希，缓存键",
  "model": "deepseek-v4-flash-vision-exp",
  "created": "ISO 时间",
  "duration": 31.6,          // 秒
  "width": 640, "height": 360,
  "has_audio": true,         // 仅元数据；模型无音频模态
  "sample_fps": 1.0,         // 宏观采样密度
  "seg_sec": 30,             // 段长（问答检索单元）
  "total_frames_extracted": 32,
  "frames_indexed": 32,      // 有卡片的帧数
  "frames": [                // 每帧一条，idx 与文件名/时间对应
    {"idx": 0, "t": 0.0,     // t = idx / sample_fps（以标签为准，不信模型回填）
     "scene": "室内鼠洞",
     "summary": "60字内画面描述",
     "keywords": ["Tom", "炸药"],
     "ocr": "画面可见文字，无则空",
     "event": "相对前帧的变化",
     "motion": "低|中|高"}   // 运动强度，微观窗口选择的依据
  ],
  "segments": [              // 帧卡片本地聚合（零成本），粗筛单元
    {"start": 0.0, "end": 30.0,
     "summary": "段内帧摘要拼接（≤600字）",
     "keywords": ["按频次排序的前10个"],
     "motion_max": "高",
     "frame_idx": [0, 1, ...]}
  ],
  "scene_cuts": [8.27, 10.8] // 本地 ffmpeg scene>0.3 检测
}
```

同目录：
- `frames/f00000.jpg ...` —— 宏观帧（idx 对齐，q3，单边 ≤3600px）
- `files.json` —— `{"0": "file-api-..."}` 帧索引 → Files API file_id（断点续传）
- `micro/<t0>_<t1>/m00000.jpg ...` —— 微观放大帧（12fps，按需生成、可复用）

## 提示词

1. **批量帧索引**（ingest `INDEX_SYSTEM`，关推理 + JSON）：每帧输出
   t/scene/summary/keywords/ocr/event/motion，t 以 `[t=Xs]` 标签为准，全覆盖不遗漏。
2. **视觉精排**（ask `RERANK_SYSTEM`，关推理 + JSON）：候选段代表帧 + 摘要，
   选最多 k 段，返回段起始秒。
3. **深读**（ask `DEEP_SYSTEM`，开推理，max_tokens=32768）：声明采样间隔，把帧序列
   当连续视频理解，论点标 `[MM:SS]`，不足则明说，≤600 字。
4. **微观**（ask `MICRO_SYSTEM`，开推理 + 32768）：1 张全图锚点 + 12fps 放大帧，
   分析快速动作与先后顺序，≤300 字。

## 关键实现约定

- 帧时刻 `t = idx / sample_fps`（fps 滤镜从 0 起规则采样），卡片 t 以标签覆盖模型值
- 微观窗口中心 = 引用时刻中**运动强度最高**者（`pick_micro_center`），
  ±1.5s，12fps，中心 40% 裁切 2x 放大
- 回显片段 = 引用时刻 ±5s，`-c copy` 无损切，失败自动重编码；HTML 内嵌上限 3 段
- 缓存失效：视频内容变 → sha 变 → 另起缓存；file_id 失效时 ask 自动重传
