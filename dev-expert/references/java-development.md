---
author: "dashboard"
---

# Java 专项开发

> 本文件是 `dev-expert` 的 Java/Spring 专项补充参考，不作为独立子技能计数，也不提供 `@` 显式调用入口。命中 Java、Spring Boot、Spring、MyBatis、Hibernate、JPA、Maven、Gradle、JUnit、Mockito、JVM、GC、线程池、并发、Java 源码分析等信号时，按需与 `code-generation`、`code-review`、`test-generation`、`performance-benchmark`、`software-project` 协同加载。

## 适用边界

- 适用：Java 项目源码走读、Spring Boot 应用开发、接口设计、数据访问、单元测试、并发分析、JVM/GC 基础诊断。
- 不适用：未确认语言/框架时强行套用 Spring 结构；Android、纯前端、PHP/CMS 项目不使用本参考。
- Java 版本：以项目 `pom.xml`、`build.gradle`、CI 和线上 JDK 为准。当前版本基线为 **Java 17 / 21 / 25**，并须区分 LTS 与 innovation 版本策略：17、21、25 为 LTS（Java 25 于 2025-09 GA），中间版本（如 22/23/24）为 innovation、仅 6 个月支持窗口，不得作为长期项目基线。目标版本特性只能在确认运行版本支持后使用。

## 源码分析流程

1. **先读结构**：查看目录、包名、模块、构建文件，识别 Controller/Service/Repository/Domain 等分层。
2. **找入口**：定位 `main` 类、Controller、Message Listener、Scheduled Task、CommandLineRunner 或核心业务入口。
3. **逐层深入**：沿调用链追踪 Controller -> Service -> Repository/Mapper -> 外部依赖，标注关键分支和异常路径。
4. **识别依赖**：梳理类间依赖、接口实现、循环依赖、配置注入和第三方组件。
5. **总结输出**：给出项目概览、核心流程、关键类职责、风险点和验证建议。

### 源码分析输出模板

```markdown
## 项目概览
- 技术栈：
- 分层架构：
- 构建工具：

## 核心流程
1. 入口：
2. 业务逻辑：
3. 数据访问：
4. 外部依赖：

## 关键类说明
| 类名 | 职责 | 关键方法 |
| --- | --- | --- |
| ... | ... | ... |

## 质量与风险
- 正确性：
- 性能：
- 安全：
- 并发：
- 建议验证：
```

## Spring Boot 标准结构

```text
src/main/java/com/example/
├── config/          # 配置类
├── controller/      # REST API 层
├── service/         # 业务逻辑层
│   └── impl/
├── repository/      # JPA Repository 或 DAO
├── mapper/          # MyBatis Mapper
├── domain/entity/   # 实体类
├── dto/             # 请求/响应 DTO
├── exception/       # 自定义异常与统一异常处理
└── util/            # 无状态工具类
```

### 常见注解速查

| 场景 | 注解 |
| - | - |
| REST Controller | `@RestController`, `@RequestMapping`, `@GetMapping`, `@PostMapping` |
| 服务层 | `@Service`, `@Transactional` |
| 仓储层 | `@Repository`, `@Mapper` |
| 依赖注入 | 构造器注入、`@RequiredArgsConstructor` |
| 配置 | `@Configuration`, `@Bean`, `@ConfigurationProperties` |
| 参数校验 | `@Valid`, `@Validated`, `@NotNull`, `@NotBlank`, `@Size` |
| 缓存 | `@Cacheable`, `@CacheEvict`, `@CachePut` |
| 异常处理 | `@RestControllerAdvice`, `@ExceptionHandler` |

## 编码规范

- 类名使用 PascalCase，方法/变量使用 camelCase，常量使用 UPPER_SNAKE_CASE。
- 优先构造器注入，避免字段注入；依赖尽量声明为接口类型。
- 不吞异常；捕获后必须记录上下文、转换为业务异常或继续抛出。
- 使用 SLF4J 日志，禁止 `System.out.println()` 进入业务代码。
- Controller 不写业务细节，Service 不直接拼 HTTP 响应，Repository/Mapper 不承载业务规则。
- `@Transactional` 放在业务边界；注意自调用、异常类型和只读事务配置。
- DTO 与 Entity 分离，禁止把 JPA Entity 直接暴露为长期 API 响应契约。
- 魔法数字、状态码、业务类型优先使用 enum 或常量表达。

## 数据访问

- JPA：关注懒加载、N+1、事务边界、级联删除、脏检查和分页查询。
- MyBatis：关注 XML/注解 SQL 参数绑定，禁止 `${}` 拼接外部输入，优先 `#{}`。
- 批量写入：使用批处理或分批提交，明确事务大小与失败回滚策略。
- 查询性能：为高频 WHERE/JOIN/ORDER BY 字段提供索引依据，必要时协同 `mysql-database`。

## 并发与异步

- 线程池必须显式配置核心线程数、最大线程数、队列长度、拒绝策略和线程名。
- `CompletableFuture` 需指定 Executor，避免默认 ForkJoinPool 被阻塞任务占满。
- 共享状态必须说明线程安全策略：不可变对象、局部变量、锁、并发集合或原子类。
- 分布式场景关注幂等、重试、超时、熔断、降级和链路追踪。
- `@Async`、调度任务、消息消费必须有异常处理和监控日志。

## 测试

- 单元测试：JUnit 5 + Mockito，隔离纯业务逻辑、边界条件和异常分支。
- Spring 集成测试：`@SpringBootTest`、`@WebMvcTest`、`@DataJpaTest` 按范围选择，避免所有测试都启动完整上下文。
- 外部依赖：数据库、Redis、MQ 可使用 Testcontainers 或测试替身。
- Web 接口：使用 MockMvc 或 WebTestClient 断言状态码、响应体和副作用。
- 每个修复缺陷至少补一条回归测试。

## JVM 与性能

基础诊断参数示例，使用前需确认线上 JDK、容器内存和运维规范。下列内容均为 **JVM 启动参数**，必须拼接到完整的 `java -jar` 命令中执行——单独作为命令执行会报 `command not found`。

```text
# 堆内存（容器内建议改用 -XX:MaxRAMPercentage 并按 limits 计算）
java -jar app.jar -Xms512m -Xmx2g

# GC 日志（JDK 9+ 统一日志框架）
java -jar app.jar -Xlog:gc*:file=gc.log:time,uptime:filecount=5,filesize=10m
```

### GC 选型对照

`-XX:+UseG1GC` 自 JDK 9 起已是服务端默认值，显式写出通常无实际作用；应按场景选择 GC：

| GC | 适用场景 | 典型参数 | 注意 |
| - | - | - | - |
| G1（JDK 9+ 默认） | 通用在线服务默认选择，堆约 4G–32G，停顿目标可调 | `-XX:+UseG1GC -XX:MaxGCPauseMillis=200` | 在线服务首选；显式指定仅用于覆盖默认或需调停顿目标 |
| ZGC（JDK 15+ 生产可用；Generational ZGC 自 JDK 21 生产可用） | 低延迟优先、大堆（数十 GB 以上）、停顿要求 < 10ms | JDK 21+：`-XX:+UseZGC -XX:+ZGenerational`；JDK 17：`-XX:+UseZGC`（非分代） | 吞吐通常略低于 G1，需以停顿时长指标换吞吐；`ZGenerational` 在 JDK 21 之前不可用 |
| Parallel（JDK 8 默认） | 吞吐优先、批处理/离线任务、可接受较长停顿 | `-XX:+UseParallelGC -XX:GCTimeRatio=99` | 停顿不可控，不适合交互式在线服务 |

选型原则：在线交互服务优先 G1；低延迟为硬要求且堆较大时评估 ZGC，JDK 21+ 使用分代 ZGC；纯批处理任务才考虑 Parallel。切换 GC 必须附带 GC 日志与停顿/吞吐对比数据，不得凭印象切换。

### Jakarta 命名空间迁移检查项

Spring Boot 2.x 已于 2023-11 结束开源支持（EOL），新项目应采用 Spring Boot 3.x+。Spring Boot 3 基于 Spring Framework 6 与 Jakarta EE 9+，`javax.*` 已整体迁移为 `jakarta.*`，这是当前 Java 项目升级中最高频的工作项。检查清单：

- 依赖注入与注解：`javax.annotation.*` → `jakarta.annotation.*`
- Servlet/Web：`javax.servlet.*` → `jakarta.servlet.*`（Filter、Listener、`HttpServletRequest`）
- 参数校验：`javax.validation.*` → `jakarta.validation.*`（`@Valid`/`@NotNull` 等注解包路径）
- 持久化：`javax.persistence.*` → `jakarta.persistence.*`（JPA Entity 注解）
- 事务与消息：`javax.transaction.*` → `jakarta.transaction.*`；`javax.jms.*` → `jakarta.jms.*`
- 第三方依赖：确认 starter 与中间件客户端存在 Jakarta 兼容版本；无兼容版本时禁止升级
- 配置项：Boot 2 → 3 的 `spring.config`、`management.*` 等属性 key 变更需逐项核对
- 验证：全量编译通过 + 应用启动成功 + 关键接口回归；`grep -rn "javax\." src/` 应无残留（第三方 SDK 内部除外）

性能问题优先采集证据：接口耗时、线程 dump、堆 dump、GC 日志、慢 SQL、连接池指标。没有基线不得声称优化有效。

## 验证命令

按项目构建工具选择：

```bash
mvn test
mvn verify
mvn spring-boot:run
./gradlew test
./gradlew build
./gradlew bootRun
```

## 关联 reference

- **code-generation**（代码生成）— 生成 Controller、Service、DTO、Repository、测试代码
- **code-review**（代码审查）— 按 Java 专项审查清单补充正确性、安全、性能、并发检查
- **test-generation**（测试用例生成）— 生成 JUnit、Mockito、Spring Boot Test、集成测试
- **performance-benchmark**（性能基准测试）— JVM、GC、线程池、接口耗时和基准对比
- **software-project**（软件项目总控）— 发布、回滚、监控、告警、巡检
