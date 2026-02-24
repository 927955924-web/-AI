"""
Knowledge base model.
"""
from django.db import models
from django.conf import settings
from core.utils import generate_id


class KnowledgeBase(models.Model):
    """Knowledge base model for storing Q&A pairs."""
    
    SOURCE_CHOICES = [
        ('manual', '手动录入'),
        ('auto_learned', '自动学习'),
        ('ai_generated', 'AI生成'),
        ('daily_analysis', '每日分析'),
    ]
    
    question = models.TextField(verbose_name='问题')
    answer = models.TextField(verbose_name='回答')
    is_correct = models.BooleanField(default=False, verbose_name='是否正确答案')
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='knowledge_items',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='knowledge_items',
        verbose_name='所有者'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='knowledge_items',
        verbose_name='关联商品'
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='manual',
        verbose_name='来源'
    )
    category = models.CharField(max_length=50, blank=True, verbose_name='分类')
    keywords = models.CharField(max_length=255, blank=True, verbose_name='关键词')
    usage_count = models.IntegerField(default=0, verbose_name='使用次数')
    
    # Vector embedding for semantic search (JSON-serialized list of floats)
    question_embedding = models.TextField(blank=True, null=True, verbose_name='问题向量')
    embedding_model = models.CharField(max_length=100, blank=True, verbose_name='向量模型')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'knowledge_base'
        verbose_name = '知识库'
        verbose_name_plural = '知识库'
        ordering = ['-is_correct', '-usage_count', '-created_at']
        indexes = [
            models.Index(fields=['shop', 'is_correct']),
            models.Index(fields=['owner']),
        ]
    
    def increment_usage(self):
        """Increment usage count."""
        self.usage_count += 1
        self.save(update_fields=['usage_count'])
    
    def mark_correct(self):
        """Mark this answer as correct."""
        self.is_correct = True
        self.save(update_fields=['is_correct', 'updated_at'])
    
    def mark_incorrect(self):
        """Mark this answer as incorrect."""
        self.is_correct = False
        self.save(update_fields=['is_correct', 'updated_at'])
    
    def __str__(self):
        return f"Q: {self.question[:50]}..."
