"""
Chat session and message models.
"""
from django.db import models
from django.conf import settings
from core.utils import generate_id


class ChatSession(models.Model):
    """Chat session model representing a conversation with a customer."""
    
    STATUS_CHOICES = [
        ('active', '进行中'),
        ('closed', '已关闭'),
        ('archived', '已归档'),
    ]
    
    session_id = models.CharField(
        max_length=50, 
        primary_key=True, 
        editable=False
    )
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        related_name='sessions',
        verbose_name='所属店铺'
    )
    customer_id = models.CharField(max_length=100, blank=True, verbose_name='客户ID')
    customer_name = models.CharField(max_length=100, blank=True, verbose_name='客户名称')
    platform = models.CharField(max_length=50, blank=True, verbose_name='平台')
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='active',
        verbose_name='状态'
    )
    last_message = models.TextField(blank=True, verbose_name='最后消息')
    metadata_json = models.JSONField(default=dict, blank=True, verbose_name='元数据')
    message_count = models.IntegerField(default=0, verbose_name='消息数')
    unread_count = models.IntegerField(default=0, verbose_name='未读数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'chat_sessions'
        verbose_name = '聊天会话'
        verbose_name_plural = '聊天会话'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['shop', 'status']),
            models.Index(fields=['customer_id']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.session_id:
            self.session_id = generate_id('cs')
        super().save(*args, **kwargs)
    
    def update_last_message(self, content: str, increment: bool = True):
        """Update last message and optionally increment message count."""
        self.last_message = content[:200] if content else ''
        if increment:
            self.message_count += 1
        self.save(update_fields=['last_message', 'message_count', 'updated_at'])
    
    def increment_unread(self, count: int = 1):
        """Increment unread count."""
        self.unread_count += count
        self.save(update_fields=['unread_count'])
    
    def reset_unread(self):
        """Reset unread count to zero."""
        self.unread_count = 0
        self.save(update_fields=['unread_count'])
    
    def close(self):
        """Close the session."""
        self.status = 'closed'
        self.save(update_fields=['status', 'updated_at'])
    
    def archive(self):
        """Archive the session."""
        self.status = 'archived'
        self.save(update_fields=['status', 'updated_at'])
    
    def reopen(self):
        """Reopen the session."""
        self.status = 'active'
        self.save(update_fields=['status', 'updated_at'])
    
    def __str__(self):
        return f"Session {self.session_id} ({self.shop.shop_name})"


class Message(models.Model):
    """Message model representing a single message in a chat session."""
    
    SENDER_TYPE_CHOICES = [
        ('customer', '客户'),
        ('agent', '客服'),
        ('ai', 'AI'),
        ('system', '系统'),
    ]
    
    MESSAGE_TYPE_CHOICES = [
        ('text', '文本'),
        ('image', '图片'),
        ('file', '文件'),
        ('order', '订单'),
        ('product', '商品'),
    ]
    
    STATUS_CHOICES = [
        ('sent', '已发送'),
        ('delivered', '已送达'),
        ('read', '已读'),
        ('failed', '发送失败'),
    ]
    
    message_id = models.CharField(
        max_length=50, 
        primary_key=True, 
        editable=False
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='所属会话'
    )
    sender_type = models.CharField(
        max_length=20, 
        choices=SENDER_TYPE_CHOICES,
        verbose_name='发送者类型'
    )
    sender_id = models.CharField(max_length=100, blank=True, verbose_name='发送者ID')
    sender_name = models.CharField(max_length=100, blank=True, verbose_name='发送者名称')
    content = models.TextField(verbose_name='消息内容')
    message_type = models.CharField(
        max_length=20, 
        choices=MESSAGE_TYPE_CHOICES, 
        default='text',
        verbose_name='消息类型'
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='sent',
        verbose_name='状态'
    )
    metadata_json = models.JSONField(default=dict, blank=True, verbose_name='元数据')
    ai_source = models.CharField(max_length=50, blank=True, verbose_name='AI来源')  # knowledge_base, cache, openai
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='时间戳')
    
    class Meta:
        db_table = 'messages'
        verbose_name = '消息'
        verbose_name_plural = '消息'
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['session', 'timestamp']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.message_id:
            self.message_id = generate_id('m')
        super().save(*args, **kwargs)
    
    def mark_as_read(self):
        """Mark message as read."""
        self.status = 'read'
        self.save(update_fields=['status'])
    
    def mark_as_delivered(self):
        """Mark message as delivered."""
        self.status = 'delivered'
        self.save(update_fields=['status'])
    
    def mark_as_failed(self):
        """Mark message as failed."""
        self.status = 'failed'
        self.save(update_fields=['status'])
    
    def __str__(self):
        return f"{self.sender_type}: {self.content[:50]}"
