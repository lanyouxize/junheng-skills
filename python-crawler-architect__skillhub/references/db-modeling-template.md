# 数据库建模模板

## 数据库建模模板

本节提供 SQLAlchemy 2.0+ ORM 数据库建模的标准模板和最佳实践。当需要设计数据库模型时，参考此技能中的模板代码。

### 标准 Base 类模板

所有模型应继承统一的 Base 类，包含通用字段：

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，包含通用字段"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        comment="更新时间"
    )
```

### 1-to-N 关系模板

用于表示层级关系（如 区县 -> 街镇 -> 小区）：

```python
from sqlalchemy import ForeignKey, String, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List


class ParentModel(Base):
    """父级实体示例"""
    __tablename__ = "parent_table"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="名称")
    code: Mapped[str] = mapped_column(String(20), unique=True, comment="编码")

    # 一对多关系：一个父级对应多个子级
    children: Mapped[List["ChildModel"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan"  # 级联删除
    )


class ChildModel(Base):
    """子级实体示例"""
    __tablename__ = "child_table"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="名称")

    # 外键关联
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("parent_table.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # 为外键创建索引
        comment="父级ID"
    )

    # 反向关系
    parent: Mapped["ParentModel"] = relationship(back_populates="children")
```

### 地理数据字段模板

用于存储位置信息的小区/POI类模型：

```python
class GeoEntity(Base):
    """包含地理信息的实体"""
    __tablename__ = "geo_entity"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), comment="详细地址")

    # 地理坐标
    longitude: Mapped[Optional[float]] = mapped_column(Float, comment="经度")
    latitude: Mapped[Optional[float]] = mapped_column(Float, comment="纬度")

    # 来源信息
    source: Mapped[Optional[str]] = mapped_column(String(50), comment="数据来源")
    source_id: Mapped[Optional[str]] = mapped_column(String(100), comment="来源唯一ID")
```

### 状态枚举模板

用于表示数据处理状态：

```python
from enum import Enum as PyEnum
from sqlalchemy import Enum


class CrawlStatus(PyEnum):
    """爬取状态枚举"""
    PENDING = "pending"        # 待爬取
    IN_PROGRESS = "in_progress"  # 爬取中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    SKIPPED = "skipped"        # 跳过


class EntityWithStatus(Base):
    """包含状态的实体"""
    __tablename__ = "entity_with_status"

    status: Mapped[CrawlStatus] = mapped_column(
        Enum(CrawlStatus),
        default=CrawlStatus.PENDING,
        comment="爬取状态"
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(1000),
        comment="错误信息"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="重试次数"
    )
```

### 数据库会话管理

```python
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


class DatabaseManager:
    """数据库连接管理器"""

    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url,
            echo=False,  # 生产环境关闭SQL日志
            pool_size=10,
            max_overflow=20
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False
        )

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def get_session(self) -> Session:
        """获取数据库会话（上下文管理器）"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

### 数据库建模最佳实践

1. **字段命名**：使用 snake_case，保持语义清晰
2. **索引设计**：外键、常用查询字段添加索引
3. **级联删除**：合理设置 `ondelete` 和 `cascade`
4. **注释完整**：每个字段添加 `comment` 说明
5. **类型注解**：使用 `Mapped[]` 进行类型标注
6. **可选字段**：使用 `Optional[]` 标记可空字段
