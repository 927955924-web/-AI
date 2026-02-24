"""
Views for products app.
"""
import csv
import io
from django.db import models
from django.db.models import Count
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from django.http import HttpResponse

from .models import Product
from .serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductListSerializer,
)


class ProductViewSet(viewsets.ModelViewSet):
    """ViewSet for product CRUD operations."""
    
    permission_classes = [IsAuthenticated]
    lookup_field = 'product_id'
    pagination_class = None  # 禁用分页，显示所有商品
    
    def get_queryset(self):
        user = self.request.user
        queryset = Product.objects.all()
        
        # Non-admin users can only see their shops' products
        if user.role != 'admin':
            queryset = queryset.filter(shop__owner=user)
        
        # Filter by shop
        shop_id = self.request.query_params.get('shop')
        if shop_id:
            queryset = queryset.filter(shop_id=shop_id)
        
        # Filter by status
        product_status = self.request.query_params.get('status')
        if product_status:
            queryset = queryset.filter(status=product_status)
        
        # Search by name or SKU
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) | 
                models.Q(sku__icontains=search)
            )
        
        return queryset.select_related('shop').annotate(
            qa_count=Count('knowledge_items')
        )
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'create':
            return ProductCreateSerializer
        return ProductSerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
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
        product = serializer.save()
        
        return Response({
            'success': True,
            'data': ProductSerializer(product).data,
            'message': '商品创建成功'
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = ProductSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        
        return Response({
            'success': True,
            'data': ProductSerializer(product).data,
            'message': '商品更新成功'
        })
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        
        return Response({
            'success': True,
            'message': '商品删除成功'
        })
    
    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def import_csv(self, request):
        """Import products from CSV file."""
        file = request.FILES.get('file')
        shop_id = request.data.get('shop')
        
        if not file:
            return Response({
                'success': False,
                'error': {'message': '请上传CSV文件'}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not shop_id:
            return Response({
                'success': False,
                'error': {'message': '请指定店铺ID'}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            decoded_file = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded_file))
            
            created_count = 0
            errors = []
            
            for row in reader:
                try:
                    Product.objects.create(
                        shop_id=shop_id,
                        sku=row.get('sku', ''),
                        name=row.get('name', row.get('商品名称', '')),
                        price=float(row.get('price', row.get('价格', 0))),
                        stock=int(row.get('stock', row.get('库存', 0))),
                        status=row.get('status', 'active'),
                        description=row.get('description', row.get('描述', '')),
                    )
                    created_count += 1
                except Exception as e:
                    errors.append(str(e))
            
            return Response({
                'success': True,
                'data': {
                    'created': created_count,
                    'errors': errors[:10]  # Limit errors shown
                },
                'message': f'成功导入{created_count}个商品'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': {'message': f'CSV解析失败: {str(e)}'}
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def export_csv(self, request):
        """Export products to CSV file."""
        queryset = self.get_queryset()
        
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="products.csv"'
        response.write('\ufeff')  # UTF-8 BOM for Excel
        
        writer = csv.writer(response)
        writer.writerow(['SKU', '商品名称', '价格', '库存', '状态', '描述'])
        
        for product in queryset:
            writer.writerow([
                product.sku,
                product.name,
                product.price,
                product.stock,
                product.status,
                product.description,
            ])
        
        return response
