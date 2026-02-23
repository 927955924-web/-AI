"""
Views for knowledge app.
"""
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import KnowledgeBase
from .services import KnowledgeService
from .serializers import (
    KnowledgeSerializer,
    KnowledgeCreateSerializer,
    KnowledgeSearchSerializer,
    KnowledgeSearchResultSerializer,
)
from core.mqtt_publisher import publish_knowledge_sync


class KnowledgeViewSet(viewsets.ModelViewSet):
    """ViewSet for knowledge base CRUD operations."""
    
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        queryset = KnowledgeBase.objects.all()
        
        # Non-admin users can only see their own knowledge
        if user.role != 'admin':
            queryset = queryset.filter(owner=user)
        
        # Filter by shop
        shop_id = self.request.query_params.get('shop')
        if shop_id:
            queryset = queryset.filter(shop_id=shop_id)
        
        # Filter by is_correct
        is_correct = self.request.query_params.get('is_correct')
        if is_correct is not None:
            queryset = queryset.filter(is_correct=is_correct.lower() == 'true')
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(question__icontains=search)
        
        # Filter by product
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        return queryset.select_related('shop', 'owner', 'product').order_by(
            'product__created_at', 'created_at'
        )
    
    def get_serializer_class(self):
        if self.action == 'create':
            return KnowledgeCreateSerializer
        return KnowledgeSerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return Response({
                'success': True,
                'data': serializer.data,
                'count': self.paginator.page.paginator.count,
            })
        
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'count': queryset.count(),
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
        knowledge = serializer.save()
        
        try:
            publish_knowledge_sync(knowledge.shop_id, 'create', knowledge.id)
        except Exception:
            pass
        
        return Response({
            'success': True,
            'data': KnowledgeSerializer(knowledge).data,
            'message': '知识库条目创建成功'
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = KnowledgeSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        knowledge = serializer.save()
        
        try:
            publish_knowledge_sync(knowledge.shop_id, 'update', knowledge.id)
        except Exception:
            pass
        
        return Response({
            'success': True,
            'data': KnowledgeSerializer(knowledge).data,
            'message': '知识库条目更新成功'
        })
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        shop_id = instance.shop_id
        knowledge_id = instance.id
        instance.delete()
        
        try:
            publish_knowledge_sync(shop_id, 'delete', knowledge_id)
        except Exception:
            pass
        
        return Response({
            'success': True,
            'message': '知识库条目删除成功'
        })
    
    @action(detail=False, methods=['post'])
    def search(self, request):
        """Search for similar questions."""
        serializer = KnowledgeSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        question = serializer.validated_data['question']
        shop_id = serializer.validated_data.get('shop')
        threshold = serializer.validated_data.get('threshold', 0.7)
        
        service = KnowledgeService(threshold=threshold)
        results = service.search_similar(
            question=question,
            shop_id=shop_id,
            owner_id=request.user.id
        )
        
        return Response({
            'success': True,
            'data': results
        })
    
    @action(detail=True, methods=['post'])
    def mark_correct(self, request, pk=None):
        """Mark a knowledge entry as correct."""
        instance = self.get_object()
        instance.mark_correct()
        
        try:
            publish_knowledge_sync(instance.shop_id, 'update', instance.id)
        except Exception:
            pass
        
        return Response({
            'success': True,
            'data': KnowledgeSerializer(instance).data,
            'message': '已标记为正确答案'
        })
    
    @action(detail=True, methods=['post'])
    def mark_incorrect(self, request, pk=None):
        """Mark a knowledge entry as incorrect."""
        instance = self.get_object()
        instance.mark_incorrect()
        
        try:
            publish_knowledge_sync(instance.shop_id, 'update', instance.id)
        except Exception:
            pass
        
        return Response({
            'success': True,
            'data': KnowledgeSerializer(instance).data,
            'message': '已标记为非正确答案'
        })
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get daily learning summary."""
        service = KnowledgeService()
        summary = service.get_daily_summary(owner_id=request.user.id)
        
        return Response({
            'success': True,
            'data': summary
        })
