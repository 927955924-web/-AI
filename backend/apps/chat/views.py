"""
Views for chat app.
"""
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import ChatSession, Message
from .serializers import (
    ChatSessionSerializer,
    ChatSessionCreateSerializer,
    ChatSessionListSerializer,
    MessageSerializer,
    MessageCreateSerializer,
)


class ChatSessionViewSet(viewsets.ModelViewSet):
    """ViewSet for chat session operations."""
    
    permission_classes = [IsAuthenticated]
    lookup_field = 'session_id'
    
    def get_queryset(self):
        user = self.request.user
        queryset = ChatSession.objects.all()
        
        # Non-admin users can only see their shops' sessions
        if user.role != 'admin':
            queryset = queryset.filter(shop__owner=user)
        
        # Filter by shop
        shop_id = self.request.query_params.get('shop')
        if shop_id:
            queryset = queryset.filter(shop_id=shop_id)
        
        # Filter by status
        session_status = self.request.query_params.get('status')
        if session_status:
            queryset = queryset.filter(status=session_status)
        
        # Search by customer name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(customer_name__icontains=search)
        
        return queryset.select_related('shop')
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ChatSessionListSerializer
        elif self.action == 'create':
            return ChatSessionCreateSerializer
        return ChatSessionSerializer
    
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
        session = serializer.save()
        
        return Response({
            'success': True,
            'data': ChatSessionSerializer(session).data,
            'message': '会话创建成功'
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def close(self, request, session_id=None):
        """Close the session."""
        session = self.get_object()
        session.close()
        
        return Response({
            'success': True,
            'data': ChatSessionSerializer(session).data,
            'message': '会话已关闭'
        })
    
    @action(detail=True, methods=['post'])
    def archive(self, request, session_id=None):
        """Archive the session."""
        session = self.get_object()
        session.archive()
        
        return Response({
            'success': True,
            'data': ChatSessionSerializer(session).data,
            'message': '会话已归档'
        })
    
    @action(detail=True, methods=['post'])
    def reopen(self, request, session_id=None):
        """Reopen the session."""
        session = self.get_object()
        session.reopen()
        
        return Response({
            'success': True,
            'data': ChatSessionSerializer(session).data,
            'message': '会话已重新打开'
        })
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, session_id=None):
        """Mark all messages as read."""
        session = self.get_object()
        session.reset_unread()
        
        return Response({
            'success': True,
            'message': '已标记为已读'
        })


class MessageListCreateView(generics.ListCreateAPIView):
    """View for listing and creating messages."""
    
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        queryset = Message.objects.all()
        
        # Non-admin users can only see their shops' messages
        if user.role != 'admin':
            queryset = queryset.filter(session__shop__owner=user)
        
        # Filter by session
        session_id = self.request.query_params.get('session')
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        
        # Limit results
        limit = self.request.query_params.get('limit', 50)
        try:
            limit = min(int(limit), 200)
        except ValueError:
            limit = 50
        
        return queryset.select_related('session')[:limit]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MessageCreateSerializer
        return MessageSerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = MessageSerializer(queryset, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        
        return Response({
            'success': True,
            'data': MessageSerializer(message).data,
            'message': '消息发送成功'
        }, status=status.HTTP_201_CREATED)


class MessageDetailView(generics.RetrieveAPIView):
    """View for retrieving a single message."""
    
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer
    lookup_field = 'message_id'
    
    def get_queryset(self):
        user = self.request.user
        queryset = Message.objects.all()
        
        if user.role != 'admin':
            queryset = queryset.filter(session__shop__owner=user)
        
        return queryset
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'data': serializer.data
        })
