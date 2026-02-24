# -*- coding: utf-8 -*-
"""
APScheduler configuration for daily conversation analysis.
Runs as a background thread within the Django process.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

_scheduler = None


def start_daily_analysis_scheduler():
    """Start the APScheduler background scheduler for daily analysis."""
    global _scheduler

    if not getattr(settings, 'DAILY_ANALYSIS_ENABLED', True):
        logger.info("[每日分析] 调度器已禁用 (DAILY_ANALYSIS_ENABLED=false)")
        return

    if _scheduler is not None:
        logger.info("[每日分析] 调度器已在运行，跳过")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        hour = getattr(settings, 'DAILY_ANALYSIS_HOUR', 2)

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(
            _run_daily_analysis,
            CronTrigger(hour=hour, minute=0, timezone='Asia/Shanghai'),
            id='daily_conversation_analysis',
            max_instances=1,
            misfire_grace_time=3600,
        )
        _scheduler.start()
        logger.info(
            f"[每日分析] 调度器已启动，每天凌晨 {hour}:00 执行"
        )
    except ImportError:
        logger.warning(
            "[每日分析] APScheduler 未安装，定时任务不可用。"
            "请安装: pip install APScheduler>=3.10"
        )
    except Exception as e:
        logger.error(f"[每日分析] 调度器启动失败: {e}")


def _run_daily_analysis():
    """Wrapper called by APScheduler to execute the daily analysis."""
    # Use distributed lock to prevent multiple gunicorn workers from running simultaneously
    from django.core.cache import cache
    lock_key = 'daily_analysis_running_lock'
    acquired = cache.add(lock_key, '1', timeout=3600)
    if not acquired:
        logger.info("[每日分析] 另一个进程正在执行，跳过")
        return

    logger.info("[每日分析] 定时任务触发，开始执行...")
    try:
        from .services_analysis import ConversationAnalysisService
        service = ConversationAnalysisService()
        summary = service.run_daily_analysis()
        logger.info(
            f"[每日分析] 定时任务完成: "
            f"记录={summary['total_records']}, "
            f"QA={summary['qa_saved']}, "
            f"删除={summary['records_deleted']}"
        )
    except Exception as e:
        logger.error(f"[每日分析] 定时任务执行失败: {e}", exc_info=True)
    finally:
        cache.delete(lock_key)
