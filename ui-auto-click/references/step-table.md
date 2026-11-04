# 步骤表写法（YAML）

## 步骤表写法（YAML）

```yaml
window:
  regex: '.*公众号.*下载工具.*'      # 标题正则（只用来排序偏好）
  classes: [Mywindow]                # 类名白名单：有它就以类名为准（标题会变）
steps:
  - name: 点获取公众号id
    action: invoke
    target:
      - {auto_id: Form.PushButton, name: "1.获取公众号id"}
      - {control_type: Button, name: "1.获取公众号id"}   # 旧版兜底
  - name: 等日志出现成功标记
    action: wait_log
    target: {auto_id: Form.TextEdit}        # 日志区（不是 PlainTextEdit！）
    contains_any: ["获取公众号历史消息页面成功", "开始获取数据"]
    timeout: 90
  - name: 等文件落盘（可选证据）
    action: wait_file
    path: 'C:/Users/Administrator/Desktop/下载/*'
    min_count: 2
    only_new: true          # 只数本次运行后新出现的，避免旧文件冒充成功
    optional: true          # 拿不到只告警，不打断流程
```

动作清单：`invoke` / `toggle` / `set_value` / `read` / `exists` / `wait_control` / `wait_log` / `assert_log` / `wait_file` / `sleep` / `screenshot` / `click`（需前台校验）/ `activate`（恢复+置前，`click` 前置）/ `open_url`（把一条链接在微信内置浏览器打开）。

`set_value` 的 `value` 支持 `${VAR}`（`--var KEY=VALUE` 注入），配 `skip_if_empty: true` 时变量为空就**跳过**（返回 `skip`，不会把退出码拉成 5）。

**条件跳步**：任一步都可以加 `when_var`，按变量值决定这一步要不要执行（不满足就返回 `skip`，同样不影响退出码）。用途是"同一位置二选一"——`${VAR}` 只能改 `value`，改不了选择器里的 `name`，而单选按钮这类互斥选项必须换 target。

```yaml
  - name: 设置时间范围（全部历史）
    action: click
    when_var: RANGE
    when_in: ["all", "全部"]      # 或 when_equals: all（单值）
    when_default: true            # 不传 RANGE 时也走这条（缺省分支）
    target: {auto_id: Form.layoutWidget.RadioButton_5, name: 全部}
  - name: 设置时间范围（一个月内）
    action: click
    when_var: RANGE
    when_in: ["monthly", "一个月内"]   # 没写 when_default：不传就跳过
    target: {auto_id: Form.layoutWidget.RadioButton_2, name: 一个月内}
```

`when_default` 只兜"变量没传"，不能变成"永远执行"；三个字段都不写＝无条件执行（既有 profile 行为不变）。

### open_url：在微信内置浏览器打开链接（取密钥那一步）

公众号下载工具的「1.获取公众号id」只产出 `profile_ext` 链接，**必须有人到微信内置浏览器里打开它**，工具才能读到 cookie 并「获取密钥成功」；否则日志只会一直刷「获取密钥失败...请先在微信打开复制的链接」，后面的下载按钮点了也白点。

```yaml
  - name: 在微信内置浏览器打开 profile_ext 链接（取密钥）
    action: open_url
    source: log          # log（UIA 直读日志正文，优先）| clipboard | value
    settle: 5            # 回车后等页面加载
    target: {auto_id: Form.TextEdit}
  - name: 等「获取密钥成功」
    action: wait_log
    contains_any: ["获取密钥成功"]
    timeout: 90
```

它内部就是三步：取链接（日志优先、剪贴板兜底）→ 点微信标题栏放大镜（模板 `templates/wechat-search.png`）→ `Ctrl+V` + `Enter`。单独跑：`python scripts/wechat_open_url.py --from-log <日志文件> | --from-clipboard | --url ...`（`--dry-run` 只报坐标）。

`source: value`（配 `value: ${VAR}`、`skip_if_empty`）可以把一条**指定**链接打开，profile 用它做
「预热」：在点「1.获取公众号id」**之前**把微信导到该号文章页。**别把预热塞进取密钥那一步的
`warmup` 参数里** —— 那时工具正在读，先跳首页会直接读错（见 `references/` 的铁律一）。

拿不到链接/微信不可用/点击失败一律**抛错中断**，不会静默往下走去点下载（那样只会等 300 秒超时，把真因埋掉）。

任一步骤都可以加 `optional: true`：失败时降级为告警并继续（适合"这台机器上那个选项是灰的"这种情况）。
