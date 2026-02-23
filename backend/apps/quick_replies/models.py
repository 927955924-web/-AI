"""
Quick reply model.
"""
from django.db import models
from django.conf import settings


class QuickReply(models.Model):
    """Quick reply template for fast customer responses."""
    
    CATEGORY_CHOICES = [
        ('greeting', '问候语'),
        ('logistics', '物流相关'),
        ('refund', '退款退货'),
        ('after_sales', '售后服务'),
        ('product', '商品咨询'),
        ('promotion', '优惠活动'),
        ('other', '其他'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quick_replies',
        verbose_name='所属用户'
    )
    title = models.CharField(max_length=50, verbose_name='标题')
    content = models.TextField(verbose_name='回复内容')
    shortcut = models.CharField(max_length=20, blank=True, verbose_name='快捷键')
    category = models.CharField(
        max_length=20, 
        choices=CATEGORY_CHOICES, 
        default='other',
        verbose_name='分类'
    )
    usage_count = models.IntegerField(default=0, verbose_name='使用次数')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'quick_replies'
        verbose_name = '快捷回复'
        verbose_name_plural = '快捷回复'
        ordering = ['sort_order', '-usage_count', '-created_at']
        indexes = [
            models.Index(fields=['user', 'category']),
            models.Index(fields=['shortcut']),
        ]
        unique_together = [['user', 'shortcut']]
    
    def increment_usage(self):
        """Increment usage count."""
        self.usage_count += 1
        self.save(update_fields=['usage_count'])
    
    def render(self, context: dict = None) -> str:
        """
        Render the content with variable replacement.
        
        Variables like {customer_name}, {order_id} will be replaced.
        """
        content = self.content
        if context:
            for key, value in context.items():
                content = content.replace(f'{{{key}}}', str(value))
        return content
    
    def __str__(self):
        return f"{self.title} ({self.shortcut})"
