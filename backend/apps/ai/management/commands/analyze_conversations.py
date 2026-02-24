# -*- coding: utf-8 -*-
"""
Management command: Analyze daily conversation records.

Usage:
    python manage.py analyze_conversations             # Analyze yesterday
    python manage.py analyze_conversations --date 2026-02-24  # Specific date
    python manage.py analyze_conversations --days 7    # Last 7 days
"""
import logging
from datetime import date, timedelta, datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '分析每日对话记录，提取Q&A到知识库，删除已处理记录'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='指定分析日期 (YYYY-MM-DD)，默认为昨天',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='分析最近N天的数据（默认1天，即昨天）',
        )

    def handle(self, *args, **options):
        from apps.ai.services_analysis import ConversationAnalysisService

        service = ConversationAnalysisService()

        # Determine dates to analyze
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
                dates = [target_date]
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    f"日期格式错误: {options['date']}，请使用 YYYY-MM-DD 格式"
                ))
                return
        else:
            days = options['days']
            today = timezone.localdate()
            dates = [today - timedelta(days=i) for i in range(1, days + 1)]

        self.stdout.write(self.style.NOTICE(
            f"准备分析 {len(dates)} 天的对话记录..."
        ))

        total_summary = {
            'total_records': 0,
            'qa_saved': 0,
            'qa_skipped': 0,
            'qa_conflicts': 0,
            'records_deleted': 0,
            'errors': [],
        }

        for target_date in sorted(dates):
            self.stdout.write(f"\n{'='*50}")
            self.stdout.write(f"分析日期: {target_date}")
            self.stdout.write(f"{'='*50}")

            try:
                summary = service.run_daily_analysis(target_date=target_date)

                # Print summary
                self.stdout.write(self.style.SUCCESS(
                    f"  对话记录: {summary['total_records']}"
                ))
                self.stdout.write(self.style.SUCCESS(
                    f"  店铺数: {summary['shops_processed']}"
                ))
                self.stdout.write(self.style.SUCCESS(
                    f"  商品组: {summary['product_groups']}, "
                    f"通用组: {summary['general_groups']}"
                ))
                self.stdout.write(self.style.SUCCESS(
                    f"  新增QA: {summary['qa_saved']}, "
                    f"跳过: {summary['qa_skipped']}, "
                    f"冲突: {summary['qa_conflicts']}"
                ))
                self.stdout.write(self.style.SUCCESS(
                    f"  删除记录: {summary['records_deleted']}"
                ))
                self.stdout.write(self.style.SUCCESS(
                    f"  耗时: {summary.get('execution_time', 0):.1f}s"
                ))

                if summary.get('errors'):
                    for err in summary['errors']:
                        self.stdout.write(self.style.WARNING(f"  警告: {err}"))

                # Accumulate totals
                total_summary['total_records'] += summary['total_records']
                total_summary['qa_saved'] += summary['qa_saved']
                total_summary['qa_skipped'] += summary['qa_skipped']
                total_summary['qa_conflicts'] += summary['qa_conflicts']
                total_summary['records_deleted'] += summary['records_deleted']
                total_summary['errors'].extend(summary.get('errors', []))

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f"  分析失败: {e}"
                ))
                logger.error(f"[每日分析命令] {target_date} 分析失败", exc_info=True)

        # Final summary
        if len(dates) > 1:
            self.stdout.write(f"\n{'='*50}")
            self.stdout.write(self.style.SUCCESS("汇总:"))
            self.stdout.write(self.style.SUCCESS(
                f"  总对话: {total_summary['total_records']}, "
                f"总QA: {total_summary['qa_saved']}, "
                f"总删除: {total_summary['records_deleted']}"
            ))

        if total_summary['errors']:
            self.stdout.write(self.style.WARNING(
                f"\n共 {len(total_summary['errors'])} 个错误"
            ))
