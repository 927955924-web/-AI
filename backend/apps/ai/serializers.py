"""
Serializers for AI app.
"""
from rest_framework import serializers
from .models import KeywordRule, SensitiveWordRule, ScenarioRule


class GenerateReplySerializer(serializers.Serializer):
    """Serializer for AI reply generation request."""
    
    question = serializers.CharField(required=True)
    context = serializers.CharField(required=False, allow_blank=True)
    session_id = serializers.CharField(required=False, allow_blank=True)
    shop_id = serializers.CharField(required=False, allow_blank=True)
    order_detail = serializers.DictField(required=False, allow_null=True)
    model = serializers.CharField(required=False, allow_blank=True)
    product_names = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    product_card_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
        help_text="Product IDs extracted from product cards in chat"
    )
    buyer_images = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
        help_text="URLs of images sent by buyer for vision analysis"
    )


class GenerateReplyResponseSerializer(serializers.Serializer):
    """Serializer for AI reply generation response."""
    
    reply = serializers.CharField()
    source = serializers.CharField()
    confidence = serializers.FloatField()
    cached = serializers.BooleanField()
    kb_id = serializers.IntegerField(required=False)
    needs_verification = serializers.BooleanField(required=False)


class IdentifyIntentSerializer(serializers.Serializer):
    """Serializer for intent identification request."""
    
    message = serializers.CharField(required=True)


class IdentifyIntentResponseSerializer(serializers.Serializer):
    """Serializer for intent identification response."""
    
    type = serializers.CharField()
    keywords = serializers.ListField(child=serializers.CharField())
    original_text = serializers.CharField()


class VisionAnalyzeSerializer(serializers.Serializer):
    """Serializer for vision analysis request."""
    
    image_base64 = serializers.CharField(required=True, help_text="Base64 encoded screenshot")
    page_type = serializers.ChoiceField(
        choices=['list', 'detail'],
        default='list',
        help_text="Page type: 'list' for product list, 'detail' for product detail"
    )
    session_id = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, default='qwen-vl-plus')
    shop_id = serializers.CharField(required=False, allow_blank=True)


class VisionAnalyzeResponseSerializer(serializers.Serializer):
    """Serializer for vision analysis response."""
    
    success = serializers.BooleanField()
    action = serializers.CharField(allow_null=True)
    data = serializers.DictField(allow_null=True)
    error = serializers.CharField(allow_null=True)
    model_used = serializers.CharField(allow_null=True)


class VisionExtractSerializer(serializers.Serializer):
    """Serializer for processing extracted product data."""
    
    extraction_data = serializers.DictField(required=True)
    session_id = serializers.CharField(required=False, allow_blank=True)
    shop_id = serializers.CharField(required=False, allow_blank=True)
    save_to_kb = serializers.BooleanField(default=True)


class SaveConversationSerializer(serializers.Serializer):
    """Serializer for saving a conversation record."""
    
    buyer_message = serializers.CharField(required=True)
    customer_reply = serializers.CharField(required=True)
    conversation_context = serializers.CharField(required=False, allow_blank=True, default='')
    buyer_name = serializers.CharField(required=False, allow_blank=True, default='')
    image_analysis = serializers.CharField(required=False, allow_blank=True, default='')
    order_info = serializers.CharField(required=False, allow_blank=True, default='')
    shop_id = serializers.CharField(required=False, allow_blank=True)
    platform = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(
        choices=['ai_auto', 'ai_kb', 'human_edited', 'debug_edited'],
        default='ai_auto'
    )
    model_used = serializers.CharField(required=False, allow_blank=True, default='')
    confidence = serializers.FloatField(required=False, default=0.0)


class SaveLearningRecordSerializer(serializers.Serializer):
    """Serializer for saving a learning record."""
    
    record_type = serializers.ChoiceField(
        choices=['product_knowledge', 'qa_pair', 'image_description'],
        default='product_knowledge'
    )
    instruction = serializers.CharField(required=True)
    response = serializers.CharField(required=True)
    product_name = serializers.CharField(required=False, allow_blank=True, default='')
    raw_knowledge = serializers.CharField(required=False, allow_blank=True, default='')
    shop_id = serializers.CharField(required=False, allow_blank=True)


class TrainingExportSerializer(serializers.Serializer):
    """Serializer for training data export request."""
    
    shop_id = serializers.CharField(required=False, allow_blank=True)
    format = serializers.ChoiceField(
        choices=['alpaca', 'sharegpt', 'jsonl'],
        default='alpaca',
        help_text="Export format: alpaca (instruction/input/output), sharegpt (conversations), jsonl (line-delimited JSON)"
    )
    quality_filter = serializers.ChoiceField(
        choices=['all', 'approved', 'unverified_and_approved'],
        default='all'
    )
    include_learning = serializers.BooleanField(default=True, help_text="Include learning records in export")
    include_conversations = serializers.BooleanField(default=True, help_text="Include conversation records in export")


class KeywordRuleSerializer(serializers.ModelSerializer):
    """Serializer for keyword trigger rules."""
    
    class Meta:
        model = KeywordRule
        fields = [
            'rule_id', 'name', 'shop', 'owner', 'platform',
            'keywords', 'match_type', 'reply_text', 'reply_image',
            'priority', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['rule_id', 'owner', 'created_at', 'updated_at']


class SensitiveWordRuleSerializer(serializers.ModelSerializer):
    """Serializer for sensitive word filtering rules."""
    
    class Meta:
        model = SensitiveWordRule
        fields = [
            'rule_id', 'name', 'shop', 'owner', 'platform',
            'sensitive_words', 'replacement',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['rule_id', 'owner', 'created_at', 'updated_at']


class ScenarioRuleSerializer(serializers.ModelSerializer):
    """Serializer for scenario monitoring rules."""
    
    class Meta:
        model = ScenarioRule
        fields = [
            'rule_id', 'name', 'shop', 'owner', 'platform',
            'scenario_type', 'detection_method',
            'trigger_condition', 'action_type', 'action_config',
            'priority', 'is_active', 'trigger_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['rule_id', 'owner', 'trigger_count', 'created_at', 'updated_at']
