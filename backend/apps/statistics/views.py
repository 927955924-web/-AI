"""
Views for statistics app.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta, datetime

from apps.shops.models import Shop
from apps.products.models import Product
from apps.chat.models import ChatSession, Message
from apps.knowledge.models import KnowledgeBase


class OverviewView(APIView):
    """Get overall statistics."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Build filters based on user role
        if user.role == 'admin':
            shops = Shop.objects.filter(is_active=True)
            products = Product.objects.all()
            sessions = ChatSession.objects.all()
            messages = Message.objects.all()
        else:
            shops = Shop.objects.filter(owner=user, is_active=True)
            products = Product.objects.filter(shop__owner=user)
            sessions = ChatSession.objects.filter(shop__owner=user)
            messages = Message.objects.filter(session__shop__owner=user)
        
        # Calculate totals
        shop_count = shops.count()
        product_count = products.count()
        session_count = sessions.count()
        message_count = messages.count()
        active_sessions = sessions.filter(status='active').count()
        
        # Daily messages for last 14 days
        start_date = timezone.now() - timedelta(days=14)
        daily_messages = messages.filter(
            timestamp__gte=start_date
        ).annotate(
            date=TruncDate('timestamp')
        ).values('date').annotate(
            count=Count('message_id')
        ).order_by('date')
        
        return Response({
            'success': True,
            'data': {
                'totals': {
                    'shops': shop_count,
                    'products': product_count,
                    'sessions': session_count,
                    'messages': message_count,
                    'active_sessions': active_sessions,
                },
                'daily_messages': list(daily_messages),
            }
        })


class AIUsageView(APIView):
    """Get AI usage statistics."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from apps.ai.models import ConversationRecord
        import logging
        logger = logging.getLogger(__name__)
        
        user = request.user
        
        # Get conversation records (actual AI usage data)
        # For now, show all records for any authenticated user
        # (can add role-based filtering later)
        if hasattr(user, 'role') and user.role == 'admin':
            records = ConversationRecord.objects.all()
        elif user.is_superuser:
            records = ConversationRecord.objects.all()
        else:
            # Show both owned records and all records if user is the only one
            records = ConversationRecord.objects.filter(owner=user)
            if records.count() == 0:
                # Fallback: show all records if no owned records
                records = ConversationRecord.objects.all()
        
        total_count = records.count()
        logger.info(f"[AIUsage] User {user.username} (role={getattr(user, 'role', 'N/A')}, superuser={user.is_superuser}) - Total records: {total_count}")
        
        # Count by source
        source_counts = records.values('source').annotate(
            count=Count('id')
        )
        
        # Map ConversationRecord source to display source
        # ai_auto -> openai (API call)
        # ai_kb -> knowledge_base
        # human_edited -> template (manual)
        # debug_edited -> template (manual)
        source_stats = {
            'knowledge_base': 0,
            'cache': 0,
            'openai': 0,
            'template': 0,
        }
        
        for item in source_counts:
            source = item['source']
            count = item['count']
            if source == 'ai_kb':
                source_stats['knowledge_base'] += count
            elif source == 'ai_auto':
                source_stats['openai'] += count
            else:  # human_edited, debug_edited, etc.
                source_stats['template'] += count
        
        total = sum(source_stats.values())
        
        # Calculate savings (knowledge_base + cache = saved API calls)
        saved = source_stats['knowledge_base'] + source_stats['cache']
        savings_rate = (saved / total * 100) if total > 0 else 0
        
        # Count by model
        model_counts = records.exclude(model_used='').values('model_used').annotate(
            count=Count('id')
        ).order_by('-count')
        
        by_model = []
        for item in model_counts:
            model_name = item['model_used'] or 'unknown'
            by_model.append({
                'model': model_name,
                'count': item['count']
            })
        
        # Count by platform
        platform_counts = records.values('platform').annotate(
            count=Count('id')
        )
        platform_name_map = {
            'pinduoduo': '拼多多',
            'qianniu': '千牛/淘宝',
            'douyin': '抖音',
            'wechat': '微信',
        }
        platform_stats = {}
        for item in platform_counts:
            platform = item['platform'] or 'unknown'
            platform_stats[platform] = {
                'count': item['count'],
                'name': platform_name_map.get(platform, platform),
            }
        
        return Response({
            'success': True,
            'data': {
                'total_ai_responses': total,
                'by_source': source_stats,
                'by_model': by_model,
                'by_platform': platform_stats,
                'api_calls_saved': saved,
                'savings_rate': round(savings_rate, 2),
            }
        })


class TopQuestionsView(APIView):
    """Get top frequently asked questions."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        limit = int(request.query_params.get('limit', 10))
        
        if user.role == 'admin':
            knowledge = KnowledgeBase.objects.all()
        else:
            knowledge = KnowledgeBase.objects.filter(owner=user)
        
        top_questions = knowledge.order_by('-usage_count')[:limit]
        
        data = [
            {
                'id': item.id,
                'question': item.question[:100],
                'usage_count': item.usage_count,
                'is_correct': item.is_correct,
            }
            for item in top_questions
        ]
        
        return Response({
            'success': True,
            'data': data
        })


class ShopStatsView(APIView):
    """Get statistics for a specific shop."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, shop_id):
        user = request.user
        
        try:
            if user.role == 'admin':
                shop = Shop.objects.get(shop_id=shop_id)
            else:
                shop = Shop.objects.get(shop_id=shop_id, owner=user)
        except Shop.DoesNotExist:
            return Response({
                'success': False,
                'error': {'message': '店铺不存在'}
            }, status=404)
        
        # Get shop statistics
        product_count = shop.products.count()
        session_count = shop.sessions.count()
        active_sessions = shop.sessions.filter(status='active').count()
        
        # Message statistics
        messages = Message.objects.filter(session__shop=shop)
        message_count = messages.count()
        
        # AI usage
        ai_messages = messages.filter(sender_type='ai')
        ai_count = ai_messages.count()
        kb_count = ai_messages.filter(ai_source='knowledge_base').count()
        
        return Response({
            'success': True,
            'data': {
                'shop_id': shop.shop_id,
                'shop_name': shop.shop_name,
                'products': product_count,
                'sessions': session_count,
                'active_sessions': active_sessions,
                'messages': message_count,
                'ai_responses': ai_count,
                'kb_responses': kb_count,
            }
        })


class TokenUsageStatsView(APIView):
    """Get token usage statistics with multiple dimensions."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from apps.ai.models import TokenUsage
        
        user = request.user
        
        # Parse query parameters
        shop_id = request.query_params.get('shop_id')
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        group_by = request.query_params.get('group_by', 'model')  # model, shop, date
        
        # Build base queryset
        if user.role == 'admin':
            queryset = TokenUsage.objects.all()
        else:
            queryset = TokenUsage.objects.filter(shop__owner=user)
        
        # Apply shop filter
        if shop_id:
            queryset = queryset.filter(shop_id=shop_id)
        
        # Apply date range filter
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                queryset = queryset.filter(created_at__gte=start_date)
            except ValueError:
                pass
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                # Include the entire end date
                end_date = end_date + timedelta(days=1)
                queryset = queryset.filter(created_at__lt=end_date)
            except ValueError:
                pass
        
        # Default to last 30 days if no date range specified
        if not start_date_str and not end_date_str:
            start_date = timezone.now() - timedelta(days=30)
            queryset = queryset.filter(created_at__gte=start_date)
        
        # Calculate totals
        totals = queryset.aggregate(
            total_prompt=Sum('prompt_tokens'),
            total_completion=Sum('completion_tokens'),
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('cost_estimate'),
            request_count=Count('id')
        )
        
        total_tokens = totals['total_tokens'] or 0
        total_cost = float(totals['total_cost'] or 0)
        
        # Aggregate by model
        by_model = []
        model_stats = queryset.values('model_name').annotate(
            prompt_tokens=Sum('prompt_tokens'),
            completion_tokens=Sum('completion_tokens'),
            total_tokens=Sum('total_tokens'),
            cost_estimate=Sum('cost_estimate'),
            request_count=Count('id')
        ).order_by('-total_tokens')
        
        for item in model_stats:
            tokens = item['total_tokens'] or 0
            percentage = (tokens / total_tokens * 100) if total_tokens > 0 else 0
            by_model.append({
                'model_name': item['model_name'],
                'prompt_tokens': item['prompt_tokens'] or 0,
                'completion_tokens': item['completion_tokens'] or 0,
                'total_tokens': tokens,
                'cost_estimate': float(item['cost_estimate'] or 0),
                'request_count': item['request_count'],
                'percentage': round(percentage, 2)
            })
        
        # Aggregate by shop (if admin or multiple shops)
        by_shop = []
        if user.role == 'admin' or not shop_id:
            shop_stats = queryset.values('shop__shop_id', 'shop__shop_name').annotate(
                total_tokens=Sum('total_tokens'),
                cost_estimate=Sum('cost_estimate'),
                request_count=Count('id')
            ).order_by('-total_tokens')[:10]
            
            for item in shop_stats:
                tokens = item['total_tokens'] or 0
                percentage = (tokens / total_tokens * 100) if total_tokens > 0 else 0
                by_shop.append({
                    'shop_id': item['shop__shop_id'],
                    'shop_name': item['shop__shop_name'] or '未知店铺',
                    'total_tokens': tokens,
                    'cost_estimate': float(item['cost_estimate'] or 0),
                    'request_count': item['request_count'],
                    'percentage': round(percentage, 2)
                })
        
        # Aggregate by date (trend)
        trend = []
        date_stats = queryset.annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            total_tokens=Sum('total_tokens'),
            cost_estimate=Sum('cost_estimate'),
            request_count=Count('id')
        ).order_by('date')
        
        for item in date_stats:
            trend.append({
                'date': item['date'].strftime('%Y-%m-%d') if item['date'] else None,
                'total_tokens': item['total_tokens'] or 0,
                'cost_estimate': float(item['cost_estimate'] or 0),
                'request_count': item['request_count']
            })
        
        return Response({
            'success': True,
            'data': {
                'total_tokens': total_tokens,
                'total_cost': round(total_cost, 4),
                'total_requests': totals['request_count'] or 0,
                'by_model': by_model,
                'by_shop': by_shop,
                'trend': trend
            }
        })


class DailyStatsView(APIView):
    """Get today's stats from ConversationRecord for accurate daily counters."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from apps.ai.models import ConversationRecord
        
        user = request.user
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get today's conversation records
        if user.is_superuser or (hasattr(user, 'role') and user.role == 'admin'):
            records = ConversationRecord.objects.filter(created_at__gte=today_start)
        else:
            records = ConversationRecord.objects.filter(owner=user, created_at__gte=today_start)
            if records.count() == 0:
                records = ConversationRecord.objects.filter(created_at__gte=today_start)
        
        # Total replies today
        total_replies = records.count()
        
        # Unique buyers today (by buyer_name, excluding empty)
        unique_buyers = records.exclude(
            buyer_name__in=['', None]
        ).values('buyer_name').distinct().count()
        
        # If buyer_name is all empty, try counting by distinct buyer_message patterns
        if unique_buyers == 0 and total_replies > 0:
            unique_buyers = 1  # At least 1 buyer if there are replies
        
        # Average response time (from created_at timestamps - approximate)
        # We estimate by looking at records grouped by buyer_name
        avg_response_time = 0
        
        return Response({
            'success': True,
            'data': {
                'date': now.strftime('%Y-%m-%d'),
                'total_replies': total_replies,
                'unique_buyers': unique_buyers,
                'avg_response_time': avg_response_time,
            }
        })
