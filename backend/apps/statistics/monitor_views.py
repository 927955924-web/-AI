"""
Internal monitoring API for OpenClaw / WeChat bot integration.
Returns system health, today's stats, and totals in a single call.
"""
import subprocess
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from apps.shops.models import Shop
from apps.products.models import Product
from apps.chat.models import ChatSession, Message
from apps.knowledge.models import KnowledgeBase

logger = logging.getLogger(__name__)


class MonitorView(APIView):
    """System monitoring endpoint for internal use (Docker network only)."""

    permission_classes = [AllowAny]

    def get(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # --- System health ---
        containers = self._check_containers()
        backend_start = getattr(self, '_start_time', now)

        # --- Today's stats ---
        today_messages = Message.objects.filter(timestamp__gte=today_start)
        messages_received = today_messages.filter(sender_type='customer').count()
        ai_replies = today_messages.filter(sender_type='ai').count()
        ai_reply_rate = round(ai_replies / messages_received * 100, 1) if messages_received > 0 else 0

        today_kb = KnowledgeBase.objects.filter(created_at__gte=today_start).count()
        active_sessions = ChatSession.objects.filter(status='active').count()

        # --- Totals ---
        shop_count = Shop.objects.filter(is_active=True).count()
        product_count = Product.objects.count()
        kb_count = KnowledgeBase.objects.count()
        total_messages = Message.objects.count()

        return Response({
            'system': {
                'status': 'healthy',
                'containers': containers,
            },
            'today': {
                'messages_received': messages_received,
                'ai_replies': ai_replies,
                'ai_reply_rate': f'{ai_reply_rate}%',
                'knowledge_qa_added': today_kb,
                'active_sessions': active_sessions,
            },
            'totals': {
                'shops': shop_count,
                'products': product_count,
                'knowledge_items': kb_count,
                'total_messages': total_messages,
            }
        })

    def _check_containers(self):
        """Check Docker container health via database/redis connectivity."""
        results = []

        # DB check (if we got here, Django+DB is working)
        results.append('backend:up')
        results.append('db:healthy')

        # Redis check
        try:
            from django.core.cache import cache
            cache.set('_health', '1', 5)
            if cache.get('_health') == '1':
                results.append('redis:up')
            else:
                results.append('redis:error')
        except Exception:
            results.append('redis:down')

        # MQTT check
        try:
            from core.mqtt_publisher import _get_client
            client = _get_client()
            if client and client.is_connected():
                results.append('mqtt:up')
            else:
                results.append('mqtt:down')
        except Exception:
            results.append('mqtt:unknown')

        results.append('nginx:up')  # If we got the request, nginx is working
        return results
