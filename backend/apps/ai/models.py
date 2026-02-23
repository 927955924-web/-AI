"""
Models for AI app - Conversation recording for local model training.
"""
from django.db import models
from django.conf import settings
from core.utils import generate_id


class ConversationRecord(models.Model):
    """
    Record buyer-customer dialogue pairs for future local model training.
    Each record represents one instruction-response pair.
    """
    
    SOURCE_CHOICES = [
        ('ai_auto', 'AI自动回复'),
        ('ai_kb', '知识库匹配回复'),
        ('human_edited', '人工编辑回复'),
        ('debug_edited', '调试编辑回复'),
    ]
    
    QUALITY_CHOICES = [
        ('unverified', '未验证'),
        ('approved', '已确认'),
        ('rejected', '已拒绝'),
    ]
    
    # Dialogue content
    buyer_message = models.TextField(verbose_name='买家消息')
    customer_reply = models.TextField(verbose_name='客服回复')
    
    # Context information
    conversation_context = models.TextField(blank=True, default='', verbose_name='对话上下文')
    buyer_name = models.CharField(max_length=100, blank=True, default='', verbose_name='买家名称')
    image_analysis = models.TextField(blank=True, default='', verbose_name='图片分析结果')
    order_info = models.TextField(blank=True, default='', verbose_name='订单信息')
    
    # Classification
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversation_records',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversation_records',
        verbose_name='所有者'
    )
    platform = models.CharField(max_length=20, blank=True, default='', verbose_name='平台')
    
    # Source and quality tracking
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='ai_auto',
        verbose_name='回复来源'
    )
    quality = models.CharField(
        max_length=20,
        choices=QUALITY_CHOICES,
        default='unverified',
        verbose_name='质量标记'
    )
    
    # AI model info
    model_used = models.CharField(max_length=50, blank=True, default='', verbose_name='使用模型')
    confidence = models.FloatField(default=0.0, verbose_name='置信度')
    
    # Training flags
    used_for_training = models.BooleanField(default=False, verbose_name='已用于训练')
    exported = models.BooleanField(default=False, verbose_name='已导出')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'ai_conversation_records'
        verbose_name = '对话记录'
        verbose_name_plural = '对话记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop', 'quality']),
            models.Index(fields=['source']),
            models.Index(fields=['quality', 'used_for_training']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Q: {self.buyer_message[:40]}... -> A: {self.customer_reply[:40]}..."


class LearningRecord(models.Model):
    """
    Record knowledge learned from product pages for training data.
    Stores raw product knowledge and generated Q&A pairs.
    """
    
    RECORD_TYPE_CHOICES = [
        ('product_knowledge', '商品知识'),
        ('qa_pair', '问答对'),
        ('image_description', '图片描述'),
    ]
    
    # Content
    record_type = models.CharField(
        max_length=30,
        choices=RECORD_TYPE_CHOICES,
        default='product_knowledge',
        verbose_name='记录类型'
    )
    instruction = models.TextField(verbose_name='指令/问题')
    response = models.TextField(verbose_name='回答/知识')
    
    # Product context
    product_name = models.CharField(max_length=255, blank=True, default='', verbose_name='商品名称')
    raw_knowledge = models.TextField(blank=True, default='', verbose_name='原始学习内容')
    
    # Classification
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='learning_records',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='learning_records',
        verbose_name='所有者'
    )
    
    # Training flags
    used_for_training = models.BooleanField(default=False, verbose_name='已用于训练')
    exported = models.BooleanField(default=False, verbose_name='已导出')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    
    class Meta:
        db_table = 'ai_learning_records'
        verbose_name = '学习记录'
        verbose_name_plural = '学习记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop', 'record_type']),
            models.Index(fields=['used_for_training']),
        ]
    
    def __str__(self):
        return f"[{self.get_record_type_display()}] {self.instruction[:50]}..."


class KeywordRule(models.Model):
    """
    Keyword trigger rules. When buyer message matches keywords,
    return a preset reply instead of calling AI.
    """
    
    MATCH_TYPE_CHOICES = [
        ('contains', '包含任意'),
        ('equals', '完全匹配'),
        ('all_contains', '包含所有'),
    ]
    
    PLATFORM_CHOICES = [
        ('', '所有平台'),
        ('taobao', '淘宝/千牛'),
        ('pdd', '拼多多'),
        ('douyin', '抖音'),
        ('wechat', '微信'),
    ]
    
    rule_id = models.CharField(max_length=50, primary_key=True, verbose_name='规则ID')
    name = models.CharField(max_length=100, verbose_name='规则名称')
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='keyword_rules',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='keyword_rules',
        verbose_name='所有者'
    )
    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        blank=True,
        default='',
        verbose_name='适用平台'
    )
    keywords = models.TextField(
        verbose_name='关键词',
        help_text='每行一个关键词'
    )
    match_type = models.CharField(
        max_length=20,
        choices=MATCH_TYPE_CHOICES,
        default='contains',
        verbose_name='匹配方式'
    )
    reply_text = models.TextField(verbose_name='预设回复')
    reply_image = models.CharField(max_length=500, blank=True, default='', verbose_name='回复图片路径')
    priority = models.IntegerField(default=0, verbose_name='优先级')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'keyword_rules'
        verbose_name = '关键词规则'
        verbose_name_plural = '关键词规则'
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['shop', 'is_active']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.rule_id:
            self.rule_id = generate_id('kr')
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"[{self.get_match_type_display()}] {self.name}"


class SensitiveWordRule(models.Model):
    """
    Sensitive word filtering rules. After AI generates a reply,
    replace sensitive words before sending.
    """
    
    PLATFORM_CHOICES = [
        ('', '所有平台'),
        ('taobao', '淘宝/千牛'),
        ('pdd', '拼多多'),
        ('douyin', '抖音'),
        ('wechat', '微信'),
    ]
    
    rule_id = models.CharField(max_length=50, primary_key=True, verbose_name='规则ID')
    name = models.CharField(max_length=100, blank=True, default='', verbose_name='规则名称')
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sensitive_word_rules',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sensitive_word_rules',
        verbose_name='所有者'
    )
    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        blank=True,
        default='',
        verbose_name='适用平台'
    )
    sensitive_words = models.TextField(
        verbose_name='敏感词',
        help_text='每行一个敏感词'
    )
    replacement = models.CharField(max_length=100, default='***', verbose_name='替换词')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'sensitive_word_rules'
        verbose_name = '敏感词规则'
        verbose_name_plural = '敏感词规则'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop', 'is_active']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.rule_id:
            self.rule_id = generate_id('sw')
        super().save(*args, **kwargs)
    
    def __str__(self):
        words = self.sensitive_words.split('\n')
        return f"敏感词: {words[0]}... -> {self.replacement}"


class ScenarioRule(models.Model):
    """
    Scenario monitoring rules. Use AI or keywords to detect customer
    intent/emotion and trigger actions like transfer to human.
    """
    
    SCENARIO_TYPE_CHOICES = [
        ('angry', '客户愤怒'),
        ('complaint', '投诉举报'),
        ('urgent', '紧急问题'),
        ('night_message', '深夜消息'),
        ('refund_request', '退款请求'),
        ('custom', '自定义'),
    ]
    
    DETECTION_METHOD_CHOICES = [
        ('ai_judge', 'AI判断'),
        ('keyword', '关键词匹配'),
        ('time_based', '时间条件'),
    ]
    
    ACTION_TYPE_CHOICES = [
        ('transfer_human', '转人工客服'),
        ('send_reply', '发送特定回复'),
        ('no_auto_reply', '不自动回复'),
        ('notify_only', '仅通知'),
    ]
    
    PLATFORM_CHOICES = [
        ('', '所有平台'),
        ('taobao', '淘宝/千牛'),
        ('pdd', '拼多多'),
        ('douyin', '抖音'),
        ('wechat', '微信'),
    ]
    
    rule_id = models.CharField(max_length=50, primary_key=True, verbose_name='规则ID')
    name = models.CharField(max_length=100, verbose_name='规则名称')
    shop = models.ForeignKey(
        'shops.Shop',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='scenario_rules',
        verbose_name='所属店铺'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='scenario_rules',
        verbose_name='所有者'
    )
    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        blank=True,
        default='',
        verbose_name='适用平台'
    )
    scenario_type = models.CharField(
        max_length=20,
        choices=SCENARIO_TYPE_CHOICES,
        default='custom',
        verbose_name='情景类型'
    )
    detection_method = models.CharField(
        max_length=20,
        choices=DETECTION_METHOD_CHOICES,
        default='ai_judge',
        verbose_name='检测方式'
    )
    trigger_condition = models.JSONField(
        default=dict,
        verbose_name='触发条件',
        help_text='AI判断: {"prompt": "..."}, 关键词: {"keywords": [...]}, 时间: {"start_hour": 22, "end_hour": 6}'
    )
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_TYPE_CHOICES,
        default='notify_only',
        verbose_name='触发动作'
    )
    action_config = models.JSONField(
        default=dict,
        verbose_name='动作配置',
        help_text='{"reply_template": "...", "notify_title": "..."}'
    )
    priority = models.IntegerField(default=0, verbose_name='优先级')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    trigger_count = models.IntegerField(default=0, verbose_name='触发次数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'scenario_rules'
        verbose_name = '情景规则'
        verbose_name_plural = '情景规则'
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['shop', 'is_active']),
            models.Index(fields=['scenario_type']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.rule_id:
            self.rule_id = generate_id('sr')
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"[{self.get_scenario_type_display()}] {self.name}"
