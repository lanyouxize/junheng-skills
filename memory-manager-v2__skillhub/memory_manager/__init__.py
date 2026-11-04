# -*- coding: utf-8 -*-
"""
Memory Manager V3.8 — WorkBuddy Memory Layer Management Expert

Modular package structure replacing monolithic memory_manager.py.
"""
VERSION = "4.0.6"
__version__ = VERSION

class MemoryManager:
    """
    V3.8 Bridge API — Programmatic interface for WorkBuddy integration.
    
    Usage:
        mm = MemoryManager("/path/to/workspace")
        result = mm.analyze()
        results = mm.search("keyword")
    """
    
    def __init__(self, workspace_path: str):
        from .config import set_lang, init_i18n
        self.workspace = workspace_path
        init_i18n()
    
    def analyze(self):
        """Scan and analyze memory directory status."""
        from .core import analyze_memory
        return analyze_memory(self.workspace)
    
    def search(self, keyword: str, folder: str = None, tag: str = None):
        """Search memories by keyword, optionally within a folder or by tag."""
        from .core import search_memory
        return search_memory(self.workspace, keyword=keyword, folder=folder, tag=tag)

    def load(self, days: int = 7, folder: str = None):
        """Load recent memories with smart ranking, optionally within a folder."""
        from .core import load_memory
        return load_memory(self.workspace, days=days, folder=folder)
    
    def rank(self):
        """Rank all memories by importance score."""
        from .core import rank_memory
        return rank_memory(self.workspace)
    
    def summarize(self):
        """Generate summaries for all memory files."""
        from .summarize import summarize_memory
        return summarize_memory(self.workspace)
    
    def token_check(self, budget: int = None):
        """Check token usage vs budget."""
        from .token import token_check, DEFAULT_DAILY_BUDGET
        return token_check(self.workspace, budget or DEFAULT_DAILY_BUDGET)

    def token_trends(self, period: str = "week", days_back: int = None):
        """Get token usage trends aggregated by day/week/month."""
        from .token import token_trends
        return token_trends(self.workspace, period=period, days_back=days_back)
    
    def cache_scan(self):
        """Read-only scan of cache state (with reminders)."""
        from .cache import cache_reminder
        return cache_reminder(self.workspace)
    
    def clean(self, dry_run: bool = True):
        """Clean orphan caches and temp files."""
        from .clean import execute_cleanup
        return execute_cleanup(self.workspace, confirm=(not dry_run))

    def dedup(self, dry_run: bool = True):
        """Deduplicate memory files by content hash."""
        from .clean import dedup_memory
        return dedup_memory(self.workspace, dry_run=dry_run, delete_dup=False)
    
    def export_data(self, output_path: str):
        """Export memories to ZIP file."""
        from .io import export_memories
        return export_memories(self.workspace, output_path)
    
    def import_data(self, input_path: str):
        """Import memories from ZIP file."""
        from .io import import_memories
        return import_memories(self.workspace, input_path)
    
    def report(self):
        """Generate full memory report."""
        from .report import generate_memory_report
        return generate_memory_report(self.workspace)

    def doctor(self):
        """Run health diagnostics."""
        from .cli import doctor_diagnose
        return doctor_diagnose(self.workspace)

    # ---- V3.10 上下文工程：选择器可见性 ----

    def selector_audit(self, stale_days: int = 30):
        """Audit memory readiness for the platform's memory selector (read-only)."""
        from .core_selector import selector_audit
        return selector_audit(self.workspace, stale_days=stale_days)

    def describe_memories(self, dry_run: bool = True, stale_days: int = 30):
        """Backfill front-matter descriptions so the selector can read each memory."""
        from .core_selector import apply_descriptions
        return apply_descriptions(self.workspace, dry_run=dry_run, stale_days=stale_days)

    def govern(self, dry_run: bool = True, stale_days: int = 30):
        """Audit (or safely fold) write-quality waste: duplicates, blanks, oversize, staleness."""
        from .core_govern import apply_govern, govern_audit
        if dry_run:
            return govern_audit(self.workspace, stale_days=stale_days)
        return apply_govern(self.workspace, dry_run=False, stale_days=stale_days)

    def snapshot(self, action: str = "create", name: str = None, label: str = "manual"):
        """Create, list, or restore memory snapshots (action: create|list|restore)."""
        from .core_snapshot import snapshot_create, snapshot_list, snapshot_restore
        if action == "list":
            return snapshot_list(self.workspace)
        if action == "restore":
            return snapshot_restore(self.workspace, name=name)
        return snapshot_create(self.workspace, label=label)

    def compact(self, dry_run: bool = True, budget: int = None):
        """Adaptively compact oversized/stale memories back under the token budget."""
        from .core_compact import apply_compact, compact_plan
        if dry_run:
            return compact_plan(self.workspace, budget=budget)
        return apply_compact(self.workspace, dry_run=False, budget=budget)

    def dashboard(self, stale_days: int = 30):
        """One-screen token savings dashboard (read-only)."""
        from .core_insight import savings_dashboard
        return savings_dashboard(self.workspace, stale_days=stale_days)

    def health(self, stale_days: int = 30):
        """Five-dimension memory health score with prioritized fixes (read-only)."""
        from .core_insight import memory_health
        return memory_health(self.workspace, stale_days=stale_days)

    def config(self, key: str = None, value: str = None):
        """View or update configuration."""
        from .config import config_memory
        return config_memory(self.workspace, key=key, value=value)

    # ---- Prompt 模板管理 ----

    def prompt_list(self, tag: str = None):
        """List all prompt templates, optionally filtered by tag."""
        from .prompt import list_prompts
        return list_prompts(self.workspace, tag=tag)

    def prompt_get(self, name: str):
        """Get prompt template content by name."""
        from .prompt import get_prompt
        return get_prompt(self.workspace, name=name)

    def prompt_save(self, name: str, content: str, tags: list = None,
                    description: str = "", category: str = ""):
        """Save or update a prompt template."""
        from .prompt import save_prompt
        return save_prompt(self.workspace, name=name, content=content,
                           tags=tags, description=description, category=category)

    def prompt_search(self, keyword: str = None, tag: str = None):
        """Search prompt templates by keyword and/or tag."""
        from .prompt import search_prompts
        return search_prompts(self.workspace, keyword=keyword, tag=tag)


# Convenience exports
from .config import _, _LANG, set_lang, load_config, save_config
from .core import analyze_memory, search_memory, load_memory, rank_memory
from .token import token_check, token_trends
from .prompt import list_prompts, get_prompt, save_prompt, search_prompts
