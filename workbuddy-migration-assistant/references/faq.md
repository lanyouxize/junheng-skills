# 最常见问题 Top 10（faq）

按症状排查，每条 = 症状 → 原因 → 一条命令/一个动作解法。报错输出首行都带稳定错误码（`[E-xxx]`），可先查下方「按错误码速查」表。冷门问题、历史版本坑见 `known-issues.md`；全流程输出样例见 `walkthrough.md`。

## 按错误码速查

| 错误码 | 含义 | 对应问题 |
|--------|------|----------|
| `E-LOCK` | WorkBuddy 数据库被占用 | 问题 1 |
| `E-PERM` | 目标路径没有写入权限 | 问题 3 |
| `E-NOTFOUND` | 路径不存在 | 问题 4 |
| `E-BADPKG` | 迁移包损坏或不是有效 zip | 问题 4 |
| `E-JSON` | 配置文件不是有效 JSON | 问题 9 |
| `E-DB` | 数据库操作失败（锁以外） | 问题 9 |
| `E-SANDBOX` | 沙箱剥写拦截 | 问题 2 |
| `E-UNKNOWN` | 未归类错误 | 问题 9 |

## 问题 1：报 `[E-LOCK] 数据库被占用，无法写入`

**原因**：WorkBuddy 客户端没退干净，或定时任务还在跑，SQLite 写锁被占。
**解法**：完全退出客户端（含系统托盘图标），确认无运行中定时任务，重跑导入（幂等可安全重试）：

```bash
python scripts/import.py --package wb.zip --profile auto
```

## 问题 2：报 `[E-SANDBOX] 沙箱剥写拦截：...`

**原因**：WorkBuddy agent 沙箱的 strip_write 策略拦截了对核心配置（settings.json 等）的写入——写操作"假成功"后文件实际没落盘，继续跑会静默丢配置。官方《常见问题·数据安全说明》明确了同一条设计：「Bash 命令沙箱 → 文件系统隔离：只能访问预先授权的工作空间目录；防沙箱逃逸：阻止对配置文件的写入」。
**解法**：关闭沙箱后重跑同一条导入命令即可。导入是幂等的，已落盘资产自动跳过，不会重复写入。

## 问题 3：报 `[E-PERM] 没有写入权限：<路径>`

**原因**：目标目录被客户端/杀毒软件占用，或终端权限不足。
**解法**：① 关客户端重试；② Windows 用管理员身份开终端再跑；③ 确认杀毒软件未锁定该目录。

## 问题 4：报 `[E-NOTFOUND]` 路径不存在 / `[E-BADPKG]` 迁移包无法读取

**原因**：路径拼写错、包没传完（传输中断）。
**解法**：包损坏时先对比源端与目标端文件大小，不一致就重传；再用 `info` 验包：

```bash
python scripts/info.py --package wb.zip
```

## 问题 5：导入成功，但新机上看不到旧对话/技能

**原因**：八成是没重启——DB、settings.json、models.json 都要重启才生效。
**解法**：完全关闭（含托盘）→ 重新打开。看导入输出尾部的 `重启后生效` / `已热加载` 两行即可知道哪些要重启。仍没有 → 查报告 `sections.verify` 的 missing 名单。

## 问题 6：跨机迁移后，旧对话能搜到但点不开 / 工作目录是旧路径

**原因**：路径映射没生效，会话 cwd 还指向旧机器路径。
**解法**：用预设重跑（幂等）：

```bash
python scripts/import.py --package wb.zip --profile auto
```

`--profile auto` = `--auto-map` + `--no-credentials`，会自动重写 DB 路径、meta.json、记忆文件里的绝对路径 token，并重建缺失的工作目录。个别路径特殊时再手工 `--path-map 旧前缀=新前缀`。

## 问题 7：迁移后所有连接器/技能都要重新授权

**原因**：跨机场景导出用了 `--no-credentials`（设计如此——OAuth token 绑机器，带过去大概率失效还占体积），或凭证本身跨机失效。
**解法**：这是预期行为。到「连接器」面板逐个重新授权即可；同机恢复备份用 `--profile backup` 导出的包并**不要**加 `--no-credentials`，凭证可原样恢复。

## 问题 8：导入报 `Cannot determine the target user_id automatically`

**原因**：新机 WorkBuddy 从未登录/从未建过对话，DB 里没有目标 uid，导入的数据会"隐身"。
**解法**：二选一——① 打开新机客户端登录并随便建一条对话后重跑；② 显式映射：

```bash
python scripts/import.py --package wb.zip --profile auto --uid-map <源uid>=<目标uid>
```

## 问题 9：报 `[E-JSON]` / `[E-DB]` / `[E-UNKNOWN]`，或校验显示 `X 项缺失`

**解法**：分三步——
1. 加 `--dry-run` 重跑一次，把问题隔离在"读"阶段；
2. 打开导入报告 `<目标>/migration-reports/import-<ts>.json`，看 `sections.verify.checks` 里 `status=partial` 项的 `missing` 名单：名单是"包里有但目标没有"的资产，通常是导入中断导致，重跑导入（幂等）即可补齐；
3. 仍不行的冷门错误查 `known-issues.md`，或到 `skill-publish-prep` 同款入口反馈。

## 问题 10：产物包（workspaces）几个 GB，微信/网盘传不动

**原因**：`--profile full` 把对话工作目录文件（代码/报告/下载）也打了包。
**解法**：两包分离就是为此设计的——主包（配置/记忆/技能/对话记录）先传先导，产物包按需补传：

```bash
# 只导主包（小，先走）
python scripts/export.py --source auto --output wb.zip --profile lite
# 新机导入主包后，产物包到手再补：
python scripts/import.py --package wb.zip --profile auto --workspaces-package wb-workspaces.zip
```

不传产物包的代价：对话历史可见可搜，但对话里生成的文件点不开，后续补传即可。

## 问题 11：官方说「更新/重装时安装目录会清空」，我的文件安全吗？

**原因**：官方《常见问题》明确——更新提示「检测到应用安装目录下存在用户项目目录」时，**安装目录会被清空并重新写入文件**；放在安装目录下的个人文件会被覆盖。
**解法**：① 别把重要项目放在 WorkBuddy 安装目录，放独立工作目录；② 换机前用本技能导出（产物包带上工作目录文件）：

```bash
python scripts/export.py --source auto --output wb.zip --profile full
```

官方同时建议「将重要文件同步保存到独立目录」——这正是产物包（`--profile full`）存在的意义。

## 问题 12：升级或隔天重启后，原工作空间文件夹消失了？

**原因**：官方《常见问题》收录了该现象（部分用户目录文件缺失，也有整个目录不见）。
**解法**：按官方口径——打开文件管理器找到原目录，通过 WorkBuddy 打开以日期或自定义名字命名的文件夹即可找回历史记录；若仍缺失，用本技能的产物包恢复（前提是迁移前导过）：

```bash
python scripts/import.py --package wb.zip --profile auto --workspaces-package wb-workspaces.zip
```

---

## 能力边界（本技能不处理什么）

- **官方错误码（1001 / 3002 / 3003 / 3007 / 6003 / 6004 / 11115 / 11133 / 11134 / 14003）**全属模型侧、网络环境与请求频控域，与本技能的迁移流程无关。遇到请查官方《错误码处理说明》，不要当作迁移失败来回滚。
- **账号登录、订阅与积分、发票账单**：均在服务端，不随本技能迁移（`usage-log.json` 等本地用量统计已在严禁迁移清单内）。
- **认证 token**（`CodeBuddyExtension/Data/auth/`）绑定机器与 authId，跨机必然失效，不在迁移范围内。

---

## 反模式提醒（踩过的坑）

- **不要在客户端开着时导入** → E-LOCK（见问题 1）
- **不要跳过 dry-run 直接导** → 冲突预览就是为这一步准备的
- **不要手动改包内 manifest.json** → 版本/校验和会失配，verify 会误报
- **不要把 `binaries/`、`logs/`、`device-id` 手工拷进目标目录** → 白名单排除它们是有原因的（平台相关/设备绑定），详见 SKILL.md「绝对不迁移的」表
- **同机恢复不要用 `--profile auto`** → 会丢凭证，用 `--auto-map`（见问题 7）
