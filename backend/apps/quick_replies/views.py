"""
Views for quick_replies app.
"""
from django.db import models
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import QuickReply
from .serializers import (
    QuickReplySerializer,
    QuickReplyCreateSerializer,
    QuickReplyRenderSerializer,
)


class QuickReplyViewSet(viewsets.ModelViewSet):
    """ViewSet for quick reply CRUD operations."""
    
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        queryset = QuickReply.objects.filter(user=user)
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by is_active
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        # Search by title or shortcut
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search) | 
                models.Q(shortcut__icontains=search)
            )
        
        return queryset
    
    def get_serializer_class(self):
        if self.action == 'create':
            return QuickReplyCreateSerializer
        return QuickReplySerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quick_reply = serializer.save()
        
        return Response({
            'success': True,
            'data': QuickReplySerializer(quick_reply).data,
            'message': '快捷回复创建成功'
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = QuickReplySerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        quick_reply = serializer.save()
        
        return Response({
            'success': True,
            'data': QuickReplySerializer(quick_reply).data,
            'message': '快捷回复更新成功'
        })
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        
        return Response({
            'success': True,
            'message': '快捷回复删除成功'
        })
    
    @action(detail=True, methods=['post'])
    def render(self, request, pk=None):
        """Render quick reply with context variables."""
        instance = self.get_object()
        serializer = QuickReplyRenderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        context = serializer.validated_data.get('context', {})
        rendered_content = instance.render(context)
        
        # Increment usage count
        instance.increment_usage()
        
        return Response({
            'success': True,
            'data': {
                'content': rendered_content,
                'original': instance.content,
            }
        })
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get list of quick reply categories."""
        categories = [
            {'value': choice[0], 'label': choice[1]}
            for choice in QuickReply.CATEGORY_CHOICES
        ]
        return Response({
            'success': True,
            'data': categories
        })
    
    @action(detail=False, methods=['get'])
    def by_shortcut(self, request):
        """Get quick reply by shortcut."""
        shortcut = request.query_params.get('shortcut', '')
        if not shortcut.startswith('/'):
            shortcut = '/' + shortcut
        
        try:
            instance = self.get_queryset().get(shortcut=shortcut, is_active=True)
            return Response({
                'success': True,
                'data': QuickReplySerializer(instance).data
            })
        except QuickReply.DoesNotExist:
            return Response({
                'success': False,
                'error': {'message': '快捷回复不存在'}
            }, status=status.HTTP_404_NOT_FOUND)
