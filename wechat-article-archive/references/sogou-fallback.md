# 备用：补链接（搜狐号）

## 备用：补链接（搜狐号）

唯一验证过可批量枚举的镜像接口：

```
https://v2.sohu.com/author-page-api/author-articles/pc/{userId}?pNo=N&size=20
```
`size` 上限 20，`pNo` 从 1 递增到返回空数组为止。返回里有 `id / title / link / publicTime`。
拿 `<userId>` 的办法：`https://mp.sohu.com/profile?xpt=<base64>` 页面里正则抓候选 userId，再逐个
调上面的接口看标题是不是目标账号的。

**⚠️ 搜狐只能补链接、不能补正文**（正文接口需鉴权）：
`edge.mp.sohu.com/api/article_data` → 403 AccessDenied；
`m.sohu.com/api/article_data` → 502；PC/移动页都是 JS 渲染，HTML 里没有正文。
另外：腾讯新闻 `i.news.qq.com/.../SearchMedia` 已 404、今日头条 author feed 需 `_signature`，
都走不通，别浪费时间。头条的 `https://www.163.com/dy/article/...`（网易）页面是服务端渲染的，
但需要逐篇搜索发现 URL，几百篇规模不现实。
