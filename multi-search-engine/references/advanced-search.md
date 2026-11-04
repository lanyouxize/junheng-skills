# 国内搜索引擎深度搜索指南

## 🔍 百度 (Baidu)

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **中文优化** | 中文内容索引最全 | `https://www.baidu.com/s?wd={keyword}` |
| **百度学术** | 学术资源搜索 | `https://xueshu.baidu.com/s?wd={keyword}` |
| **百度新闻** | 新闻聚合 | `https://news.baidu.com/` |

### 搜索示例

```javascript
// 1. 基础搜索
web_fetch({"url": "https://www.baidu.com/s?wd=Python教程"})

// 2. 站内搜索
web_fetch({"url": "https://www.baidu.com/s?wd=site:github.com+python"})

// 3. 文件类型搜索
web_fetch({"url": "https://www.baidu.com/s?wd=机器学习+filetype:pdf"})

// 4. 学术搜索
web_fetch({"url": "https://xueshu.baidu.com/s?wd=深度学习+图像识别"})
```

---

## 🔎 必应中国版 (Bing CN/INT)

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **中文优化** | `ensearch=0` 中文结果 | `https://cn.bing.com/search?q={keyword}&ensearch=0` |
| **国际版** | `ensearch=1` 英文结果 | `https://cn.bing.com/search?q={keyword}&ensearch=1` |
| **学术搜索** | 学术资源 | `https://cn.bing.com/academic/search?q={keyword}` |

### 搜索示例

```javascript
// 1. 中文搜索结果
web_fetch({"url": "https://cn.bing.com/search?q=人工智能技术&ensearch=0"})

// 2. 英文搜索结果（使用中国服务器）
web_fetch({"url": "https://cn.bing.com/search?q=artificial+intelligence&ensearch=1"})

// 3. 学术搜索
web_fetch({"url": "https://cn.bing.com/academic/search?q=机器学习算法"})
```

---

## 🔍 360搜索

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **安全搜索** | 内置安全防护 | 默认开启 |
| **基础搜索** | 网页搜索 | `https://www.so.com/s?q={keyword}` |

### 搜索示例

```javascript
// 1. 基础搜索
web_fetch({"url": "https://www.so.com/s?q=网络安全"})

// 2. 站内搜索
web_fetch({"url": "https://www.so.com/s?q=site:zhihu.com+python"})
```

---

## 🔍 搜狗 (Sogou) + 微信搜索

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **网页搜索** | 通用搜索 | `https://sogou.com/web?query={keyword}` |
| **微信公众号** | 搜公众号文章（唯一渠道） | `https://wx.sogou.com/weixin?type=2&query={keyword}` |
| **知乎优化** | 知乎内容索引好 | `site:zhihu.com` 配合使用 |

### 搜索示例

```javascript
// 1. 网页搜索
web_fetch({"url": "https://sogou.com/web?query=python教程"})

// 2. 微信公众号文章搜索
web_fetch({"url": "https://wx.sogou.com/weixin?type=2&query=Python编程"})

// 3. 搜索特定公众号
web_fetch({"url": "https://wx.sogou.com/weixin?type=2&query=公众号:机器之心"})

// 4. 知乎内容搜索
web_fetch({"url": "https://www.sogou.com/web?query=site:zhihu.com+机器学习"})
```

---

## 📰 头条搜索 (Toutiao)

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **基础搜索** | 综合结果（含资讯/视频/微头条混合） | `https://so.toutiao.com/search?keyword={keyword}` |
| **PC 版式** | 指定 PC 渲染，结果更完整 | `https://so.toutiao.com/search?dvpf=pc&keyword={keyword}&pd=synthesis` |
| **垂类切换** | `pd=` 指定内容类型（见下表） | `https://so.toutiao.com/search?dvpf=pc&keyword={keyword}&pd={type}` |

### pd 分类参数（实测可用取值）

| `pd=` 取值 | 对应分类 |
|-----------|---------|
| `synthesis` | 综合 |
| `information` | 资讯 |
| `video` | 视频 |
| `atlas` | 图片 |
| `user` | 用户 |
| `weitoutiao` | 微头条 |
| `xiaoshipin` | 小视频 |
| `music` | 音乐 |

### 搜索示例

```javascript
// 1. 基础搜索
web_fetch({"url": "https://so.toutiao.com/search?keyword=宠物食品"})

// 2. 只要资讯
web_fetch({"url": "https://so.toutiao.com/search?dvpf=pc&keyword=宠物食品&pd=information"})

// 3. 只要视频
web_fetch({"url": "https://so.toutiao.com/search?dvpf=pc&keyword=宠物食品&pd=video"})

// 4. 微头条（短内容/爆料）
web_fetch({"url": "https://so.toutiao.com/search?dvpf=pc&keyword=宠物食品&pd=weitoutiao"})
```

> **实测说明**（2026-10-12）：
> ① `pd=` 分类取自真实返回页面（`so.toutiao.com` 的版式切换入口），各取值返回体量不同，确为独立频道。
> ② `site:` 操作符实测**生效**：对照 `keyword=python` 得 0 条知乎链接，`keyword=site:zhihu.com python` 得 29 条。
> ③ `filetype:` **未能可靠判定**——同一 URL 两次抓取的 `.pdf` 计数在 0/4/68 间波动（页面为动态渲染），
> 故此处不作声明；需要严格文件类型检索时建议改用百度或必应。

---

## 📱 神马搜索 (Shenma)

### 特色功能

| 功能 | 说明 | URL |
|------|------|-----|
| **移动优化** | 专注移动端搜索 | `https://m.sm.cn/s?q={keyword}` |
| **阿里生态** | 整合阿里系内容 | UC浏览器默认搜索 |

### 搜索示例

```javascript
// 1. 移动端搜索
web_fetch({"url": "https://m.sm.cn/s?q=python入门教程"})

// 2. 移动网站点搜索
web_fetch({"url": "https://m.sm.cn/s?q=site:zhuanlan.zhihu.com+AI"})
```

---

## 🌍 国内搜索策略

### 按搜索目标选择引擎

| 搜索目标 | 首选引擎 | 原因 |
|---------|---------|------|
| **综合中文内容** | 百度 | 中文索引最全 |
| **微信公众号** | 搜狗微信 | 唯一支持公众号搜索 |
| **知乎内容** | 搜狗 | 知乎优化好 |
| **移动端内容** | 神马 | 移动端优化 |
| **学术资源** | 必应学术 | 学术索引 |
| **中英文双语** | 必应中国/国际版 | enswitch切换 |
| **新闻资讯** | 百度新闻 | 新闻聚合 |
| **自媒体/热点/短视频** | 头条 | 资讯、微头条、视频聚合 |

---

## 📚 参考资料

- [百度搜索高级语法](https://baike.baidu.com/item/搜索语法)
- [必应搜索技巧](https://cn.bing.com/tips)
- [搜狗搜索帮助](https://help.sogou.com/)
- [头条搜索](https://so.toutiao.com/)
