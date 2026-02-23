"""
Shop model and related models.
"""
from django.db import models
from django.conf import settings
from core.utils import generate_id


class Shop(models.Model):
    """Shop model representing an e-commerce store."""
    
    PLATFORM_CHOICES = [
        ('taobao', '淘宝/天猫'),
        ('jd', '京东'),
        ('pdd', '拼多多'),
        ('douyin', '抖音'),
        ('kuaishou', '快手'),
        ('xianyu', '闲鱼'),
        ('wechat', '微信'),
        ('xiaohongshu', '小红书'),
        ('other', '其他'),
    ]
    
    STATUS_CHOICES = [
        ('inactive', '未启动'),
        ('running', '运行中'),
        ('stopped', '已停止'),
    ]
    
    shop_id = models.CharField(
        max_length=50, 
        primary_key=True, 
        editable=False
    )
    shop_name = models.CharField(max_length=100, verbose_name='店铺名称')
    account = models.CharField(max_length=100, verbose_name='登录账号')
    password = models.CharField(max_length=255, verbose_name='登录密码')  # Encrypted
    login_url = models.URLField(max_length=500, blank=True, verbose_name='登录地址')
    platform_type = models.CharField(
        max_length=20, 
        choices=PLATFORM_CHOICES, 
        default='taobao',
        verbose_name='平台类型'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shops',
        verbose_name='所有者'
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='inactive',
        verbose_name='状态'
    )
    config_json = models.JSONField(default=dict, blank=True, verbose_name='配置')
    notes = models.TextField(blank=True, verbose_name='备注/知识库')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'shops'
        verbose_name = '店铺'
        verbose_name_plural = '店铺'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'platform_type']),
            models.Index(fields=['status']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.shop_id:
            self.shop_id = generate_id('s')
        super().save(*args, **kwargs)
    
    def start(self):
        """Start the shop monitoring."""
        self.status = 'running'
        self.save(update_fields=['status', 'updated_at'])
    
    def stop(self):
        """Stop the shop monitoring."""
        self.status = 'stopped'
        self.save(update_fields=['status', 'updated_at'])
    
    def update_config(self, key: str, value):
        """Update a specific config key."""
        self.config_json[key] = value
        self.save(update_fields=['config_json', 'updated_at'])
    
    def get_config(self, key: str, default=None):
        """Get a specific config value."""
        return self.config_json.get(key, default)
    
    def __str__(self):
        return f"{self.shop_name} ({self.get_platform_type_display()})"
