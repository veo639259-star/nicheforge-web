"""NicheForge Phase 3 — browser-track utilities.

Sub-package for browser automation: image queue management, paste-safe
handoff points, competitor harvesting and comment mining. All runners ship
with DRY-RUN mode (default) so nothing touches a real account until Hmb
flips the switch.

Safety core (mimic, sentinel, guard): strictly sequential 1-by-1 browser
work, never parallel; never hammer a rate limit; never auto-retry a
captcha or block.
"""

try:  # package context: from browser_track import ...
    from browser_track.mimic import (
        MimicConfig,
        TaskQueue,
        human_sleep,
        init_mimic_tables,
        list_tasks,
        random_mouse_move,
        type_text,
    )
    from browser_track.sentinel import (
        LIMIT_SIGNALS,
        RateLimitTracker,
        check_status_code,
        check_text,
    )
    from browser_track.guard import BLOCK_SIGNALS, BlockGuard, scan
except ImportError:  # direct module context
    from mimic import (
        MimicConfig,
        TaskQueue,
        human_sleep,
        init_mimic_tables,
        list_tasks,
        random_mouse_move,
        type_text,
    )
    from sentinel import (
        LIMIT_SIGNALS,
        RateLimitTracker,
        check_status_code,
        check_text,
    )
    from guard import BLOCK_SIGNALS, BlockGuard, scan

__all__ = [
    "MimicConfig",
    "TaskQueue",
    "human_sleep",
    "init_mimic_tables",
    "list_tasks",
    "random_mouse_move",
    "type_text",
    "LIMIT_SIGNALS",
    "RateLimitTracker",
    "check_status_code",
    "check_text",
    "BLOCK_SIGNALS",
    "BlockGuard",
    "scan",
]
