"""
User model and related models.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from core.utils import generate_id


class User(AbstractUser):
    """Custom User model for the e-commerce customer service system."""
    
    ROLE_CHOICES = [
        ('admin', '管理员'),
        ('user', '普通用户'),
        ('guest', '访客'),
    ]
    
    user_id = models.CharField(
        max_length=50, 
        unique=True, 
        editable=False,
        db_index=True
    )
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True, verbose_name='手机号')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user', verbose_name='角色')
    vip_status = models.BooleanField(default=False, verbose_name='VIP状态')
    vip_expiry = models.DateTimeField(null=True, blank=True, verbose_name='VIP过期时间')
    invite_code = models.CharField(max_length=20, unique=True, null=True, blank=True, verbose_name='邀请码')
    invited_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='invitees',
        verbose_name='邀请人'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.user_id:
            self.user_id = generate_id('u')
        if not self.invite_code:
            self.invite_code = generate_id('inv')[:12]
        super().save(*args, **kwargs)
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission based on role."""
        permissions = {
            'admin': ['manage_users', 'manage_shops', 'view_stats', 'system_config'],
            'user': ['manage_own_shops', 'view_own_stats', 'use_ai_service'],
            'guest': ['view_public'],
        }
        return permission in permissions.get(self.role, [])
    
    def renew_vip(self, days: int):
        """Renew VIP status for specified days."""
        from django.utils import timezone
        from datetime import timedelta
        
        self.vip_status = True
        now = timezone.now()
        if self.vip_expiry and self.vip_expiry > now:
            self.vip_expiry += timedelta(days=days)
        else:
            self.vip_expiry = now + timedelta(days=days)
        self.save(update_fields=['vip_status', 'vip_expiry'])
    
    def __str__(self):
        return f"{self.username} ({self.role})"


class SystemSettings(models.Model):
    """System-wide settings stored as key-value pairs."""
    
    key = models.CharField(max_length=100, primary_key=True, verbose_name='设置键')
    value = models.TextField(verbose_name='设置值')
    is_secret = models.BooleanField(default=False, verbose_name='是否敏感')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'system_settings'
        verbose_name = '系统设置'
        verbose_name_plural = '系统设置'
    
    def __str__(self):
        return self.key
