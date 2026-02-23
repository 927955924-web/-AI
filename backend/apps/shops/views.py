"""
Views for shops app.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from core.permissions import IsOwnerOrAdmin
from .models import Shop
from .serializers import (
    ShopSerializer,
    ShopCreateSerializer,
    ShopUpdateSerializer,
    ShopListSerializer,
)


class ShopViewSet(viewsets.ModelViewSet):
    """ViewSet for shop CRUD operations."""
    
    permission_classes = [IsAuthenticated]
    lookup_field = 'shop_id'
    
    def get_queryset(self):
        user = self.request.user
        queryset = Shop.objects.filter(is_active=True)
        
        # Non-admin users can only see their own shops
        if user.role != 'admin':
            queryset = queryset.filter(owner=user)
        
        # Filter by platform_type if provided
        platform = self.request.query_params.get('platform')
        if platform:
            queryset = queryset.filter(platform_type=platform)
        
        # Filter by status if provided
        shop_status = self.request.query_params.get('status')
        if shop_status:
            queryset = queryset.filter(status=shop_status)
        
        # Search by name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(shop_name__icontains=search)
        
        return queryset.select_related('owner')
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ShopSerializer  # Use full serializer to include config_json
        elif self.action == 'create':
            return ShopCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ShopUpdateSerializer
        return ShopSerializer
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy', 'start', 'stop']:
            return [IsAuthenticated(), IsOwnerOrAdmin()]
        return super().get_permissions()
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        
        # Manually ensure config_json is included
        for i, shop in enumerate(queryset):
            data[i]['config_json'] = shop.config_json or {}
        
        return Response({
            'success': True,
            'data': data
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
        shop = serializer.save()
        
        return Response({
            'success': True,
            'data': ShopSerializer(shop).data,
            'message': '店铺创建成功'
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        shop = serializer.save()
        
        return Response({
            'success': True,
            'data': ShopSerializer(shop).data,
            'message': '店铺更新成功'
        })
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Soft delete
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        
        return Response({
            'success': True,
            'message': '店铺删除成功'
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def start(self, request, shop_id=None):
        """Start shop monitoring."""
        shop = self.get_object()
        shop.start()
        shop.last_login = timezone.now()
        shop.save(update_fields=['last_login'])
        
        return Response({
            'success': True,
            'data': ShopSerializer(shop).data,
            'message': '店铺已启动'
        })
    
    @action(detail=True, methods=['post'])
    def stop(self, request, shop_id=None):
        """Stop shop monitoring."""
        shop = self.get_object()
        shop.stop()
        
        return Response({
            'success': True,
            'data': ShopSerializer(shop).data,
            'message': '店铺已停止'
        })
    
    @action(detail=False, methods=['get'])
    def platforms(self, request):
        """Get list of supported platforms."""
        platforms = [
            {'value': choice[0], 'label': choice[1]}
            for choice in Shop.PLATFORM_CHOICES
        ]
        return Response({
            'success': True,
            'data': platforms
        })
