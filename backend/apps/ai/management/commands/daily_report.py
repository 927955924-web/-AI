# -*- coding: utf-8 -*-
"""
Management command: Generate daily statistics report and send to WeChat.

Usage:
    python manage.py daily_report                    # Generate and send report
    python manage.py daily_report --dry-run          # Preview without sending
    python manage.py daily_report --date 2026-02-24  # Specific date report
    python manage.py daily_report --period weekly    # Weekly report
"""
import os
import logging
import requests
from datetime import date, timedelta, datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q
from django.db.models.functions import TruncDate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '生成每日客服对话统计报表，分析AI回复质量，并推送到微信'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='指定统计日期 (YYYY-MM-DD)，默认为昨天',
        )
        parser.add_argument(
            '--period',
            type=str,
            choices=['daily', 'weekly', 'monthly'],
            default='daily',
            help='报表周期: daily(日报), weekly(周报), monthly(月报)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅预览报表，不发送通知',
        )
        parser.add_argument(
            '--channel',
            type=str,
            choices=['pushplus', 'serverchan', 'wecom'],
            default='pushplus',
            help='通知渠道: pushplus, serverchan, wecom(企业微信)',
        )

    def handle(self, *args, **options):
        from apps.ai.models import ConversationRecord, TokenUsage
        from apps.chat.models import ChatSession, Message
        from apps.shops.models import Shop

        # Determine date range
        if options['date']:
            try:
                end_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    f"日期格式错误: {options['date']}，请使用 YYYY-MM-DD 格式"
                ))
                return
        else:
            end_date = timezone.localdate() - timedelta(days=1)

        period = options['period']
        if period == 'daily':
            start_date = end_date
            period_name = f"{end_date} 日报"
        elif period == 'weekly':
            start_date = end_date - timedelta(days=6)
            period_name = f"{start_date} ~ {end_date} 周报"
        else:  # monthly
            start_date = end_date.replace(day=1)
            period_name = f"{start_date.strftime('%Y年%m月')} 月报"

        self.stdout.write(self.style.NOTICE(f"正在生成 {period_name}..."))

        # Build date range filter
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        # ============ 1. 对话统计 ============
        conversation_stats = ConversationRecord.objects.filter(
            created_at__range=(start_dt, end_dt)
        ).aggregate(
            total=Count('id'),
            ai_auto=Count('id', filter=Q(source='ai_auto')),
            ai_kb=Count('id', filter=Q(source='ai_kb')),
            human_edited=Count('id', filter=Q(source='human_edited')),
            approved=Count('id', filter=Q(quality='approved')),
            rejected=Count('id', filter=Q(quality='rejected')),
            avg_confidence=Avg('confidence'),
        )

        # ============ 2. Token使用统计 ============
        token_stats = TokenUsage.objects.filter(
            created_at__range=(start_dt, end_dt)
        ).aggregate(
            sum_tokens=Sum('total_tokens'),
            sum_cost=Sum('cost_estimate'),
            chat_tokens=Sum('total_tokens', filter=Q(request_type='chat')),
            vision_tokens=Sum('total_tokens', filter=Q(request_type='vision')),
            qa_tokens=Sum('total_tokens', filter=Q(request_type='qa_generation')),
        )

        # 按模型统计
        model_usage = TokenUsage.objects.filter(
            created_at__range=(start_dt, end_dt)
        ).values('model_name').annotate(
            tokens=Sum('total_tokens'),
            cost=Sum('cost_estimate'),
            count=Count('id'),
        ).order_by('-tokens')

        # ============ 3. 会话统计 ============
        session_stats = ChatSession.objects.filter(
            created_at__range=(start_dt, end_dt)
        ).aggregate(
            total_sessions=Count('session_id'),
            total_messages=Sum('message_count'),
        )

        # ============ 4. AI回复来源分布 ============
        ai_messages = Message.objects.filter(
            sender_type='ai',
            timestamp__range=(start_dt, end_dt)
        )
        ai_source_stats = ai_messages.values('ai_source').annotate(
            count=Count('message_id')
        )

        # ============ 5. 店铺维度统计 ============
        shop_stats = ConversationRecord.objects.filter(
            created_at__range=(start_dt, end_dt)
        ).values('shop__shop_name').annotate(
            total=Count('id'),
            ai_count=Count('id', filter=Q(source__in=['ai_auto', 'ai_kb'])),
        ).order_by('-total')[:5]  # Top 5 shops

        # ============ 6. 计算AI回复质量指标 ============
        total_conv = conversation_stats['total'] or 0
        ai_auto = conversation_stats['ai_auto'] or 0
        ai_kb = conversation_stats['ai_kb'] or 0
        approved = conversation_stats['approved'] or 0
        rejected = conversation_stats['rejected'] or 0
        human_edited = conversation_stats['human_edited'] or 0

        ai_reply_rate = (ai_auto + ai_kb) / total_conv * 100 if total_conv > 0 else 0
        approval_rate = approved / total_conv * 100 if total_conv > 0 else 0
        rejection_rate = rejected / total_conv * 100 if total_conv > 0 else 0
        human_rate = human_edited / total_conv * 100 if total_conv > 0 else 0
        avg_confidence = conversation_stats['avg_confidence'] or 0

        total_tokens = token_stats['sum_tokens'] or 0
        total_cost = token_stats['sum_cost'] or Decimal('0')

        # ============ 生成HTML报表 ============
        model_rows = ""
        if model_usage:
            for m in model_usage:
                name = m['model_name'] or '未知'
                tokens = m['tokens'] or 0
                cost = m['cost'] or 0
                count = m['count'] or 0
                model_rows += f'''
                <tr>
                    <td>{name}</td>
                    <td>{tokens:,}</td>
                    <td>¥{float(cost):.4f}</td>
                    <td>{count}</td>
                </tr>'''

        shop_rows = ""
        if shop_stats:
            for i, s in enumerate(shop_stats, 1):
                name = s['shop__shop_name'] or '未知'
                total_s = s['total'] or 0
                ai_count = s['ai_count'] or 0
                shop_rows += f'''
                <tr>
                    <td>{i}</td>
                    <td>{name}</td>
                    <td>{total_s}</td>
                    <td>{ai_count}</td>
                </tr>'''

        sessions = session_stats['total_sessions'] or 0
        messages = session_stats['total_messages'] or 0
        avg_msg = messages / sessions if sessions > 0 else 0

        report_time = timezone.localtime().strftime('%Y-%m-%d %H:%M')

        html_content = f'''
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 16px;">
    
    <div style="text-align: center; color: white; margin-bottom: 20px;">
        <h1 style="margin: 0; font-size: 24px;">📊 AI客服{period_name}</h1>
        <p style="margin: 5px 0 0; opacity: 0.9; font-size: 14px;">{report_time}</p>
    </div>

    <!-- 核心指标卡片 -->
    <div style="display: flex; gap: 10px; margin-bottom: 15px;">
        <div style="flex: 1; background: white; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <div style="font-size: 28px; font-weight: bold; color: #667eea;">{total_conv}</div>
            <div style="color: #666; font-size: 12px;">总对话</div>
        </div>
        <div style="flex: 1; background: white; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <div style="font-size: 28px; font-weight: bold; color: #10b981;">{ai_reply_rate:.1f}%</div>
            <div style="color: #666; font-size: 12px;">AI回复率</div>
        </div>
        <div style="flex: 1; background: white; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <div style="font-size: 28px; font-weight: bold; color: #f59e0b;">{avg_confidence:.0%}</div>
            <div style="color: #666; font-size: 12px;">置信度</div>
        </div>
    </div>

    <!-- 对话统计 -->
    <div style="background: white; border-radius: 12px; padding: 15px; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
        <h3 style="margin: 0 0 12px; color: #333; font-size: 16px;">📈 对话概览</h3>
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="color: #666;">AI自动回复</span>
            <span style="font-weight: bold; color: #10b981;">{ai_auto} 条</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="color: #666;">知识库匹配</span>
            <span style="font-weight: bold; color: #3b82f6;">{ai_kb} 条</span>
        </div>
        <div style="display: flex; justify-content: space-between;">
            <span style="color: #666;">人工编辑</span>
            <span style="font-weight: bold; color: #8b5cf6;">{human_edited} 条</span>
        </div>
    </div>

    <!-- 质量评估 -->
    <div style="background: white; border-radius: 12px; padding: 15px; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
        <h3 style="margin: 0 0 12px; color: #333; font-size: 16px;">✅ AI回复质量</h3>
        <div style="margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="color: #666;">已确认</span>
                <span style="color: #10b981; font-weight: bold;">{approved} ({approval_rate:.1f}%)</span>
            </div>
            <div style="background: #e5e7eb; border-radius: 4px; height: 8px; overflow: hidden;">
                <div style="background: linear-gradient(90deg, #10b981, #34d399); height: 100%; width: {min(approval_rate, 100)}%;"></div>
            </div>
        </div>
        <div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="color: #666;">已拒绝</span>
                <span style="color: #ef4444; font-weight: bold;">{rejected} ({rejection_rate:.1f}%)</span>
            </div>
            <div style="background: #e5e7eb; border-radius: 4px; height: 8px; overflow: hidden;">
                <div style="background: linear-gradient(90deg, #ef4444, #f87171); height: 100%; width: {min(rejection_rate, 100)}%;"></div>
            </div>
        </div>
    </div>

    <!-- Token消耗 -->
    <div style="background: white; border-radius: 12px; padding: 15px; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
        <h3 style="margin: 0 0 12px; color: #333; font-size: 16px;">💰 Token消耗</h3>
        <div style="display: flex; justify-content: space-around; text-align: center;">
            <div>
                <div style="font-size: 20px; font-weight: bold; color: #667eea;">{total_tokens:,}</div>
                <div style="color: #666; font-size: 12px;">总Token</div>
            </div>
            <div style="width: 1px; background: #e5e7eb;"></div>
            <div>
                <div style="font-size: 20px; font-weight: bold; color: #f59e0b;">¥{float(total_cost):.2f}</div>
                <div style="color: #666; font-size: 12px;">预估成本</div>
            </div>
        </div>
    </div>

    <!-- 模型使用 -->
    {f"""
    <div style="background: white; border-radius: 12px; padding: 15px; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
        <h3 style="margin: 0 0 12px; color: #333; font-size: 16px;">🤖 模型使用分布</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <tr style="background: #f3f4f6;">
                <th style="padding: 8px; text-align: left; color: #666;">模型</th>
                <th style="padding: 8px; text-align: left; color: #666;">Tokens</th>
                <th style="padding: 8px; text-align: left; color: #666;">成本</th>
                <th style="padding: 8px; text-align: left; color: #666;">次数</th>
            </tr>
            {model_rows}
        </table>
    </div>
    """ if model_rows else ""}

    <!-- 店铺排行 -->
    {f"""
    <div style="background: white; border-radius: 12px; padding: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
        <h3 style="margin: 0 0 12px; color: #333; font-size: 16px;">🏪 店铺对话排行</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <tr style="background: #f3f4f6;">
                <th style="padding: 8px; text-align: left; color: #666;">#</th>
                <th style="padding: 8px; text-align: left; color: #666;">店铺</th>
                <th style="padding: 8px; text-align: left; color: #666;">对话</th>
                <th style="padding: 8px; text-align: left; color: #666;">AI</th>
            </tr>
            {shop_rows}
        </table>
    </div>
    """ if shop_rows else ""}

</div>
'''

        # 同时生成文本版本用于控制台输出
        report_lines = [
            f"📊 AI客服{period_name}",
            f"总对话: {total_conv} | AI回复率: {ai_reply_rate:.1f}% | 置信度: {avg_confidence:.0%}",
            f"Token: {total_tokens:,} | 成本: ¥{float(total_cost):.4f}",
        ]
        report_content = "\n".join(report_lines)

        # Print report
        self.stdout.write(self.style.SUCCESS("\n" + "="*50))
        self.stdout.write(report_content)
        self.stdout.write("="*50)

        # Send notification
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("\n[预览模式] 未发送通知"))
            return

        channel = options['channel']
        success = self.send_notification(
            title=f"AI客服{period_name}",
            content=html_content,
            channel=channel,
            template='html'
        )

        if success:
            self.stdout.write(self.style.SUCCESS(f"\n✅ 报表已发送到 {channel}"))
        else:
            self.stderr.write(self.style.ERROR(f"\n❌ 发送失败，请检查 {channel} 配置"))

    def send_notification(self, title: str, content: str, channel: str, template: str = 'html') -> bool:
        """Send notification to WeChat via specified channel."""
        
        if channel == 'pushplus':
            return self._send_pushplus(title, content, template)
        elif channel == 'serverchan':
            return self._send_serverchan(title, content)
        elif channel == 'wecom':
            return self._send_wecom(title, content)
        return False

    def _send_pushplus(self, title: str, content: str, template: str = 'html') -> bool:
        """
        Send via PushPlus (推送加) - https://www.pushplus.plus/
        Set PUSHPLUS_TOKEN in environment variables.
        """
        token = os.environ.get('PUSHPLUS_TOKEN')
        if not token:
            self.stderr.write(self.style.WARNING(
                "未配置 PUSHPLUS_TOKEN 环境变量，请访问 https://www.pushplus.plus/ 获取"
            ))
            return False

        try:
            resp = requests.post(
                'https://www.pushplus.plus/send',
                json={
                    'token': token,
                    'title': title,
                    'content': content,
                    'template': template,
                },
                timeout=10
            )
            result = resp.json()
            if result.get('code') == 200:
                return True
            else:
                self.stderr.write(f"PushPlus错误: {result.get('msg')}")
                return False
        except Exception as e:
            self.stderr.write(f"PushPlus请求失败: {e}")
            return False

    def _send_serverchan(self, title: str, content: str) -> bool:
        """
        Send via Server酱 - https://sct.ftqq.com/
        Set SERVERCHAN_KEY in environment variables.
        """
        key = os.environ.get('SERVERCHAN_KEY')
        if not key:
            self.stderr.write(self.style.WARNING(
                "未配置 SERVERCHAN_KEY 环境变量，请访问 https://sct.ftqq.com/ 获取"
            ))
            return False

        try:
            resp = requests.post(
                f'https://sctapi.ftqq.com/{key}.send',
                data={
                    'title': title,
                    'desp': content,
                },
                timeout=10
            )
            result = resp.json()
            if result.get('code') == 0:
                return True
            else:
                self.stderr.write(f"Server酱错误: {result.get('message')}")
                return False
        except Exception as e:
            self.stderr.write(f"Server酱请求失败: {e}")
            return False

    def _send_wecom(self, title: str, content: str) -> bool:
        """
        Send via 企业微信群机器人 Webhook.
        Set WECOM_WEBHOOK in environment variables.
        """
        webhook = os.environ.get('WECOM_WEBHOOK')
        if not webhook:
            self.stderr.write(self.style.WARNING(
                "未配置 WECOM_WEBHOOK 环境变量，请在企业微信群中添加机器人获取Webhook地址"
            ))
            return False

        try:
            resp = requests.post(
                webhook,
                json={
                    'msgtype': 'markdown',
                    'markdown': {
                        'content': f"## {title}\n\n{content}"
                    }
                },
                timeout=10
            )
            result = resp.json()
            if result.get('errcode') == 0:
                return True
            else:
                self.stderr.write(f"企业微信错误: {result.get('errmsg')}")
                return False
        except Exception as e:
            self.stderr.write(f"企业微信请求失败: {e}")
            return False
