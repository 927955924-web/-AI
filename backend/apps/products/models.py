"""
Product model.
"""
from django.db import models
from core.utils import generate_id


class Product(models.Model):
    """Product model representing a product in a shop."""
    
    STATUS_CHOICES = [
        ('active', '在售'),
        ('inactive', '下架'),
    ]
    
    LEARNING_STATUS_CHOICES = [
        ('pending', '待学习'),
        ('learned', '已学习'),
        ('failed', '学习失败'),
    ]
    
    product_id = models.CharField(
        max_length=50, 
        primary_key=True, 
        editable=False
    )
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name='所属店铺'
    )
    platform_product_id = models.CharField(
        max_length=100, 
        blank=True, 
        default='',
        verbose_name='平台商品ID',
        help_text='电商平台原始商品ID'
    )
    sku = models.CharField(max_length=100, blank=True, verbose_name='SKU')
    name = models.CharField(max_length=255, verbose_name='商品名称')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='价格')
    stock = models.IntegerField(default=0, verbose_name='库存')
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='active',
        verbose_name='状态'
    )
    description = models.TextField(blank=True, verbose_name='描述')
    image_url = models.URLField(max_length=500, blank=True, verbose_name='图片URL')
    specs_json = models.JSONField(default=dict, blank=True, verbose_name='规格参数JSON')
    learning_status = models.CharField(
        max_length=20,
        choices=LEARNING_STATUS_CHOICES,
        default='pending',
        verbose_name='学习状态'
    )
    learned_at = models.DateTimeField(null=True, blank=True, verbose_name='学习时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'products'
        verbose_name = '商品'
        verbose_name_plural = '商品'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['shop', 'status']),
            models.Index(fields=['sku']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.product_id:
            self.product_id = generate_id('p')
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.sku})"
