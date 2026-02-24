# -*- coding: utf-8 -*-
"""
API views for learning tasks.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import LearningTask
from .services import LearningService
from .serializers import (
    StartLearningSerializer,
    LearningTaskSerializer,
    ProductDataSerializer,
    ProductDataResponseSerializer,
)


class StartLearningView(APIView):
    """
    启动知识库学习任务
    POST /api/v1/learning/start/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = StartLearningSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        shop_id = serializer.validated_data['shop_id']
        platform = serializer.validated_data['platform']
        
        # Check if there's already a running task for this shop
        existing_task = LearningTask.objects.filter(
            shop_id=shop_id,
            status__in=['pending', 'running']
        ).first()
        
        if existing_task:
            return Response({
                'success': False,
                'error': {
                    'code': 'TASK_EXISTS',
                    'message': '该店铺已有正在进行的学习任务'
                },
                'data': LearningTaskSerializer(existing_task).data
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create new task
        service = LearningService()
        task = service.create_task(
            shop_id=shop_id,
            platform=platform,
            owner_id=request.user.id
        )
        
        return Response({
            'success': True,
            'data': LearningTaskSerializer(task).data
        })


class LearningTaskStatusView(APIView):
    """
    获取学习任务状态
    GET /api/v1/learning/status/<task_id>/
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, task_id):
        try:
            task = LearningTask.objects.get(task_id=task_id)
        except LearningTask.DoesNotExist:
            return Response({
                'success': False,
                'error': {
                    'code': 'NOT_FOUND',
                    'message': '任务不存在'
                }
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check ownership (non-admin can only see their own tasks)
        if not request.user.is_staff and task.owner_id != request.user.id:
            return Response({
                'success': False,
                'error': {
                    'code': 'FORBIDDEN',
                    'message': '无权访问此任务'
                }
            }, status=status.HTTP_403_FORBIDDEN)
        
        return Response({
            'success': True,
            'data': LearningTaskSerializer(task).data
        })


class UpdateTaskProgressView(APIView):
    """Update task progress (called by Electron client)."""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, task_id):
        try:
            task = LearningTask.objects.get(task_id=task_id)
        except LearningTask.DoesNotExist:
            return Response({
                'success': False,
                'error': {'message': '任务不存在'}
            }, status=status.HTTP_404_NOT_FOUND)
        
        total = request.data.get('total_products')
        if total is not None:
            task.total_products = total
            task.status = 'running'
            task.save(update_fields=['total_products', 'status'])
            task.add_log(f'开始学习，共 {total} 个商品')
        
        return Response({'success': True})


class ProcessProductView(APIView):
    """
    处理单个商品数据（由Electron客户端调用）
    POST /api/v1/learning/process-product/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ProductDataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        task_id = serializer.validated_data['task_id']
        
        try:
            task = LearningTask.objects.get(task_id=task_id)
        except LearningTask.DoesNotExist:
            return Response({
                'success': False,
                'error': {'message': '任务不存在'}
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Process the product
        service = LearningService()
        result = service.process_product(task, serializer.validated_data)
        
        return Response(result)


class CompleteTaskView(APIView):
    """Mark task as completed."""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, task_id):
        try:
            task = LearningTask.objects.get(task_id=task_id)
        except LearningTask.DoesNotExist:
            return Response({
                'success': False,
                'error': {'message': '任务不存在'}
            }, status=status.HTTP_404_NOT_FOUND)
        
        service = LearningService()
        service.complete_task(task)
        
        return Response({
            'success': True,
            'data': LearningTaskSerializer(task).data
        })


class ResetAllTasksView(APIView):
    """Reset all stuck learning tasks (pending/running) to failed."""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        count = LearningTask.objects.filter(
            status__in=['pending', 'running']
        ).update(status='failed')
        
        return Response({
            'success': True,
            'data': {'reset_count': count}
        })


class CheckProductLearnedView(APIView):
    """
    检查商品是否已学习过
    POST /api/v1/learning/check-learned/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        shop_id = request.data.get('shop_id')
        platform_product_id = request.data.get('platform_product_id')
        
        if not shop_id or not platform_product_id:
            return Response({
                'success': False,
                'error': {'message': '缺少shop_id或platform_product_id'}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        service = LearningService()
        result = service.check_product_learned(shop_id, platform_product_id)
        
        return Response({
            'success': True,
            'data': result
        })


class ResolveConflictView(APIView):
    """
    解决知识冲突
    POST /api/v1/learning/resolve-conflict/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        conflict_id = request.data.get('conflict_id')
        action = request.data.get('action')  # 'keep_old', 'use_new', 'merge'
        new_answer = request.data.get('new_answer', '')
        
        if not conflict_id or not action:
            return Response({
                'success': False,
                'error': {'message': '缺少conflict_id或action'}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        service = LearningService()
        result = service.resolve_conflict(
            conflict_id=int(conflict_id),
            action=action,
            new_answer=new_answer
        )
        
        return Response(result)
