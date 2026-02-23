"""
Views for statistics app.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta

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
        user = request.user
        
        # Get messages with AI source
        if user.role == 'admin':
            ai_messages = Message.objects.filter(sender_type='ai')
        else:
            ai_messages = Message.objects.filter(
                session__shop__owner=user,
                sender_type='ai'
            )
        
        # Count by source
        source_counts = ai_messages.values('ai_source').annotate(
            count=Count('message_id')
        )
        
        source_stats = {
            'knowledge_base': 0,
            'cache': 0,
            'openai': 0,
            'template': 0,
        }
        
        for item in source_counts:
            source = item['ai_source'] or 'template'
            if source in source_stats:
                source_stats[source] = item['count']
        
        total = sum(source_stats.values())
        
        # Calculate savings (knowledge_base + cache = saved API calls)
        saved = source_stats['knowledge_base'] + source_stats['cache']
        savings_rate = (saved / total * 100) if total > 0 else 0
        
        return Response({
            'success': True,
            'data': {
                'total_ai_responses': total,
                'by_source': source_stats,
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
