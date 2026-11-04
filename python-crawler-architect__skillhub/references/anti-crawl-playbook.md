# 反爬虫策略模板

## 反爬虫策略模板

本节提供生产级爬虫所需的反爬虫策略和稳定性工程模板代码，包括代理池、断点续传、重试机制等核心组件。

### 代理池管理器

```python
import random
import asyncio
from typing import Optional, List, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import aiohttp


@dataclass
class Proxy:
    """代理实体"""
    host: str
    port: int
    protocol: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    fail_count: int = 0
    last_used: Optional[datetime] = None
    last_fail: Optional[datetime] = None

    @property
    def url(self) -> str:
        """生成代理URL"""
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    def mark_failed(self):
        """标记失败"""
        self.fail_count += 1
        self.last_fail = datetime.now()

    def reset_fail_count(self):
        """重置失败计数"""
        self.fail_count = 0


class ProxyPool:
    """
    代理池管理器

    功能：
    - 代理轮换
    - 失效代理自动剔除
    - 代理健康检查
    """

    def __init__(
        self,
        max_fail_count: int = 3,
        check_interval: int = 300,
        test_url: str = "http://httpbin.org/ip"
    ):
        self.proxies: List[Proxy] = []
        self.blacklist: Set[str] = set()
        self.max_fail_count = max_fail_count
        self.check_interval = check_interval
        self.test_url = test_url
        self._lock = asyncio.Lock()

    def add_proxy(self, proxy: Proxy):
        """添加代理"""
        if proxy.url not in self.blacklist:
            self.proxies.append(proxy)

    def add_proxies_from_list(self, proxy_list: List[str]):
        """从字符串列表批量添加代理（格式: host:port 或 protocol://host:port）"""
        for proxy_str in proxy_list:
            if "://" in proxy_str:
                protocol, rest = proxy_str.split("://")
                host, port = rest.split(":")
            else:
                protocol = "http"
                host, port = proxy_str.split(":")
            self.add_proxy(Proxy(host=host, port=int(port), protocol=protocol))

    async def get_proxy(self) -> Optional[str]:
        """获取一个可用代理"""
        async with self._lock:
            available = [p for p in self.proxies if p.fail_count < self.max_fail_count]
            if not available:
                return None
            proxy = random.choice(available)
            proxy.last_used = datetime.now()
            return proxy.url

    async def report_failure(self, proxy_url: str):
        """报告代理失败"""
        async with self._lock:
            for proxy in self.proxies:
                if proxy.url == proxy_url:
                    proxy.mark_failed()
                    if proxy.fail_count >= self.max_fail_count:
                        self.blacklist.add(proxy_url)
                        self.proxies.remove(proxy)
                    break

    async def report_success(self, proxy_url: str):
        """报告代理成功"""
        async with self._lock:
            for proxy in self.proxies:
                if proxy.url == proxy_url:
                    proxy.reset_fail_count()
                    break

    async def health_check(self, timeout: int = 10) -> int:
        """健康检查所有代理，返回可用代理数量"""
        async def check_single(proxy: Proxy) -> bool:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.test_url,
                        proxy=proxy.url,
                        timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as resp:
                        return resp.status == 200
            except Exception:
                return False

        tasks = [check_single(p) for p in self.proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_count = 0
        async with self._lock:
            for proxy, is_valid in zip(self.proxies[:], results):
                if is_valid is True:
                    proxy.reset_fail_count()
                    valid_count += 1
                else:
                    proxy.mark_failed()

        return valid_count
```

### 断点续传状态管理器

```python
import json
import os
from typing import Dict, Set, Any, Optional
from datetime import datetime
from pathlib import Path


class StateManager:
    """
    爬虫状态管理器（支持断点续传）

    功能：
    - 记录已完成的任务ID
    - 保存爬取进度
    - 支持文件持久化
    """

    def __init__(self, state_file: str = "crawler_state.json"):
        self.state_file = Path(state_file)
        self.completed_ids: Set[str] = set()
        self.progress: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}
        self._load_state()

    def _load_state(self):
        """从文件加载状态"""
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.completed_ids = set(data.get("completed_ids", []))
                self.progress = data.get("progress", {})
                self.metadata = data.get("metadata", {})

    def save_state(self):
        """保存状态到文件"""
        data = {
            "completed_ids": list(self.completed_ids),
            "progress": self.progress,
            "metadata": {
                **self.metadata,
                "last_saved": datetime.now().isoformat()
            }
        }
        # 先写入临时文件，再重命名（原子操作）
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.rename(self.state_file)

    def mark_completed(self, task_id: str):
        """标记任务完成"""
        self.completed_ids.add(task_id)

    def is_completed(self, task_id: str) -> bool:
        """检查任务是否已完成"""
        return task_id in self.completed_ids

    def update_progress(self, key: str, value: Any):
        """更新进度信息"""
        self.progress[key] = value

    def get_progress(self, key: str, default: Any = None) -> Any:
        """获取进度信息"""
        return self.progress.get(key, default)

    def clear(self):
        """清除所有状态"""
        self.completed_ids.clear()
        self.progress.clear()
        if self.state_file.exists():
            self.state_file.unlink()
```

### 请求重试装饰器

```python
import asyncio
import functools
from typing import TypeVar, Callable, Any
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_async(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    异步重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 退避系数（每次重试延迟乘以此系数）
        exceptions: 需要重试的异常类型

    Usage:
        @retry_async(max_retries=3, delay=1.0)
        async def fetch_data(url):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"第 {attempt + 1}/{max_retries + 1} 次尝试失败: {e}. "
                            f"{current_delay:.1f}秒后重试..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"所有 {max_retries + 1} 次尝试均失败: {e}")

            raise last_exception

        return wrapper
    return decorator
```

### User-Agent 轮换

```python
import random


class UserAgentRotator:
    """User-Agent 轮换器"""

    # 常用桌面浏览器 UA
    DESKTOP_UAS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    # 移动端 UA
    MOBILE_UAS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ]

    def __init__(self, include_mobile: bool = False):
        self.user_agents = self.DESKTOP_UAS.copy()
        if include_mobile:
            self.user_agents.extend(self.MOBILE_UAS)

    def get_random(self) -> str:
        """获取随机 User-Agent"""
        return random.choice(self.user_agents)

    def get_headers(self) -> dict:
        """获取带随机 UA 的请求头"""
        return {
            "User-Agent": self.get_random(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
```

### 请求频率限制器

```python
import asyncio
import time
from typing import Optional


class RateLimiter:
    """
    令牌桶限流器

    用于控制请求频率，避免触发反爬虫机制
    """

    def __init__(self, rate: float, burst: int = 1):
        """
        Args:
            rate: 每秒允许的请求数
            burst: 突发容量（令牌桶大小）
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        获取一个令牌

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            是否成功获取令牌
        """
        start_time = time.monotonic()

        while True:
            async with self._lock:
                now = time.monotonic()
                # 补充令牌
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True

            # 检查超时
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    return False

            # 等待令牌
            wait_time = (1 - self.tokens) / self.rate
            await asyncio.sleep(min(wait_time, 0.1))

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        pass
```

### 反爬虫策略最佳实践

1. **代理池初始化**：启动时进行一次健康检查，剔除无效代理
2. **状态定期保存**：每处理 N 个任务或每隔 M 分钟保存一次状态
3. **限流参数调优**：根据目标网站的承受能力调整请求频率
4. **异常分类处理**：区分临时错误（网络超时）和永久错误（404）
5. **日志完整记录**：记录每次请求的代理、状态和耗时
