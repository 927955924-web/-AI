# -*- coding: utf-8 -*-
"""
Learning task models for auto-learning product knowledge.
"""
import uuid
from django.db import models
from django.conf import settings


class LearningTask(models.Model):
    """
    Represents a product learning task for a shop.
    """
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('running', '进行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    
    task_id = models.CharField(
        max_length=50, 
        primary_key=True, 
        default=uuid.uuid4,
        verbose_name='任务ID'
    )
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        related_name='learning_tasks',
        verbose_name='店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='learning_tasks',
        verbose_name='所有者'
    )
    platform = models.CharField(
        max_length=20,
        verbose_name='平台',
        help_text='pdd/taobao/douyin'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='状态'
    )
    total_products = models.IntegerField(default=0, verbose_name='总商品数')
    processed_count = models.IntegerField(default=0, verbose_name='已处理数')
    success_count = models.IntegerField(default=0, verbose_name='成功数')
    fail_count = models.IntegerField(default=0, verbose_name='失败数')
    qa_generated = models.IntegerField(default=0, verbose_name='生成问答数')
    logs = models.JSONField(default=list, verbose_name='日志')
    started_at = models.DateTimeField(auto_now_add=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    
    class Meta:
        db_table = 'learning_task'
        verbose_name = '学习任务'
        verbose_name_plural = '学习任务'
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.shop.shop_name} - {self.get_status_display()}"
    
    def add_log(self, message: str, level: str = 'info'):
        """Add a log entry to the task."""
        from django.utils import timezone
        log_entry = {
            'time': timezone.now().strftime('%H:%M:%S'),
            'level': level,
            'message': message
        }
        self.logs.append(log_entry)
        # Keep only last 100 logs
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        self.save(update_fields=['logs'])
    
    def update_progress(self, processed: int = None, success: int = None, fail: int = None):
        """Update task progress counters."""
        update_fields = []
        if processed is not None:
            self.processed_count = processed
            update_fields.append('processed_count')
        if success is not None:
            self.success_count = success
            update_fields.append('success_count')
        if fail is not None:
            self.fail_count = fail
            update_fields.append('fail_count')
        if update_fields:
            self.save(update_fields=update_fields)
    
    def mark_completed(self):
        """Mark task as completed."""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])
    
    def mark_failed(self, error_message: str = None):
        """Mark task as failed."""
        from django.utils import timezone
        self.status = 'failed'
        self.completed_at = timezone.now()
        if error_message:
            self.add_log(error_message, level='error')
        self.save(update_fields=['status', 'completed_at'])
