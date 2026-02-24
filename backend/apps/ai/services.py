# -*- coding: utf-8 -*-
"""
AI service for generating replies and knowledge base learning.
"""
import json
import logging
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, F
from core.utils import md5_hash
from apps.knowledge.services import KnowledgeService

logger = logging.getLogger(__name__)

# Model health check cache keys and constants
MODEL_HEALTH_CACHE_PREFIX = 'model_health:'
MODEL_HEALTH_CHECK_INTERVAL = 600  # 10 minutes in seconds
MODEL_HEALTH_TTL = 660  # Slightly longer than check interval

# Global health check thread reference
_health_check_thread = None
_health_check_stop_event = threading.Event()


class KeywordFilterService:
    """Service for keyword trigger rules and sensitive word filtering."""
    
    def check_keyword_trigger(
        self,
        question: str,
        shop_id: str = None,
        platform: str = '',
        owner_id: int = None
    ) -> Optional[Dict[str, Any]]:
        """
        Check if buyer message matches any keyword trigger rule.
        Returns preset reply dict if matched, None otherwise.
        """
        from .models import KeywordRule
        
        rules = KeywordRule.objects.filter(is_active=True)
        
        # Filter by shop (shop-specific + global rules)
        if shop_id:
            rules = rules.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        else:
            rules = rules.filter(shop__isnull=True)
        
        # Filter by platform
        if platform:
            rules = rules.filter(Q(platform=platform) | Q(platform=''))
        else:
            rules = rules.filter(platform='')
        
        rules = rules.order_by('-priority', '-created_at')
        
        question_stripped = question.strip()
        
        for rule in rules:
            keywords = [k.strip() for k in rule.keywords.split('\n') if k.strip()]
            if not keywords:
                continue
            
            matched = False
            if rule.match_type == 'contains':
                matched = any(k in question_stripped for k in keywords)
            elif rule.match_type == 'equals':
                matched = question_stripped in keywords
            elif rule.match_type == 'all_contains':
                matched = all(k in question_stripped for k in keywords)
            
            if matched:
                logger.info(f"[KeywordTrigger] Rule '{rule.name}' matched for: {question_stripped[:50]}")
                return {
                    'reply': rule.reply_text,
                    'source': 'keyword_trigger',
                    'rule_id': rule.rule_id,
                    'rule_name': rule.name,
                    'confidence': 1.0,
                    'cached': False,
                }
        
        return None
    
    def filter_sensitive_words(
        self,
        text: str,
        shop_id: str = None,
        platform: str = '',
        owner_id: int = None
    ) -> str:
        """
        Replace sensitive words in AI reply text.
        Returns filtered text.
        """
        from .models import SensitiveWordRule
        
        if not text:
            return text
        
        rules = SensitiveWordRule.objects.filter(is_active=True)
        
        if shop_id:
            rules = rules.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        else:
            rules = rules.filter(shop__isnull=True)
        
        if platform:
            rules = rules.filter(Q(platform=platform) | Q(platform=''))
        else:
            rules = rules.filter(platform='')
        
        result = text
        replaced_count = 0
        
        for rule in rules:
            words = [w.strip() for w in rule.sensitive_words.split('\n') if w.strip()]
            for word in words:
                if word in result:
                    result = result.replace(word, rule.replacement)
                    replaced_count += 1
        
        if replaced_count > 0:
            logger.info(f"[SensitiveFilter] Replaced {replaced_count} sensitive words")
        
        return result


class ScenarioMonitorService:
    """Service for scenario monitoring - detect customer intent/emotion and trigger actions."""
    
    def evaluate(
        self,
        question: str,
        context: str = None,
        shop_id: str = None,
        platform: str = '',
        owner_id: int = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate if buyer message triggers any scenario rule.
        Returns scenario result dict if triggered, None otherwise.
        """
        from .models import ScenarioRule
        
        rules = ScenarioRule.objects.filter(is_active=True)
        
        if shop_id:
            rules = rules.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        else:
            rules = rules.filter(shop__isnull=True)
        
        if platform:
            rules = rules.filter(Q(platform=platform) | Q(platform=''))
        else:
            rules = rules.filter(platform='')
        
        rules = rules.order_by('-priority', '-created_at')
        
        for rule in rules:
            triggered = False
            
            if rule.detection_method == 'keyword':
                triggered = self._check_keyword(question, rule.trigger_condition)
            elif rule.detection_method == 'time_based':
                triggered = self._check_time(rule.trigger_condition)
            elif rule.detection_method == 'ai_judge':
                triggered = self._check_ai_judge(question, context, rule.trigger_condition)
            
            if triggered:
                # Increment trigger count
                ScenarioRule.objects.filter(rule_id=rule.rule_id).update(
                    trigger_count=rule.trigger_count + 1
                )
                
                logger.info(f"[ScenarioMonitor] Rule '{rule.name}' triggered, action: {rule.action_type}")
                
                return {
                    'triggered': True,
                    'rule_id': rule.rule_id,
                    'rule_name': rule.name,
                    'scenario_type': rule.scenario_type,
                    'action': rule.action_type,
                    'action_config': rule.action_config,
                    'reason': f"触发规则: {rule.name}",
                }
        
        return None
    
    def _check_keyword(self, question: str, condition: dict) -> bool:
        """Check if message contains any trigger keywords."""
        keywords = condition.get('keywords', [])
        if not keywords:
            return False
        return any(k in question for k in keywords if k)
    
    def _check_time(self, condition: dict) -> bool:
        """Check if current time falls within specified range."""
        start_hour = condition.get('start_hour', 22)
        end_hour = condition.get('end_hour', 6)
        current_hour = datetime.now().hour
        
        if start_hour > end_hour:
            # Overnight range (e.g., 22:00 - 06:00)
            return current_hour >= start_hour or current_hour < end_hour
        else:
            # Same-day range (e.g., 09:00 - 18:00)
            return start_hour <= current_hour < end_hour
    
    def _check_ai_judge(self, question: str, context: str, condition: dict) -> bool:
        """Use AI to judge if message matches scenario condition."""
        prompt_template = condition.get('prompt', '判断客户是否需要人工服务')
        
        try:
            ai_service = AIService()
            judge_question = (
                f"请判断以下客户消息是否符合条件：{prompt_template}\n"
                f"客户消息：{question}\n"
                f"只回答true或false，不要有其他内容"
            )
            result = ai_service._call_llm(
                judge_question, context, None, model='deepseek-v3.2'
            )
            if result:
                return 'true' in result.strip().lower()
        except Exception as e:
            logger.error(f"[ScenarioMonitor] AI judge failed: {e}")
        
        return False


class AIService:
    """
    AI service that implements knowledge-base-first strategy to save credits.
    
    Flow:
    1. Search knowledge base for similar questions
    2. If correct answer found -> return it (source: knowledge_base)
    3. Check cache for previous AI responses
    4. If cached -> return it (source: cache)
    5. Call OpenAI API (source: openai)
    6. Save response to knowledge base and cache
    """
    
    # Mapping from model config api_key_setting to database key
    API_KEY_DB_MAPPING = {
        'DEEPSEEK_API_KEY': 'deepseek_api_key',
        'QWEN_API_KEY': 'qwen_api_key',
        'DOUBAO_API_KEY': 'doubao_api_key',
        'OPENAI_API_KEY': 'openai_api_key',
        'GEMINI_API_KEY': 'gemini_api_key',
    }
    
    # Token pricing per 1K tokens (in CNY)
    # DeepSeek: input(cache miss)=0.002, input(cache hit)=0.0002, output=0.003
    # Using cache miss rate for input as conservative estimate
    # Qwen pricing updated 2026-02: turbo 0.3/0.6, plus 0.8/2, max 2.4/9.6 per million tokens
    TOKEN_PRICING = {
        'deepseek': {'input': 0.002, 'output': 0.008},  # DeepSeek V3: 2/8 元/百万tokens
        'qwen': {'input': 0.0003, 'output': 0.0006},    # Qwen Turbo (default model)
        'qwen-turbo': {'input': 0.0003, 'output': 0.0006},
        'qwen-plus': {'input': 0.0008, 'output': 0.002},
        'qwen-max': {'input': 0.0024, 'output': 0.0096},
        'qwen-flash': {'input': 0.00015, 'output': 0.0015},
        'doubao': {'input': 0.0032, 'output': 0.016},  # Doubao Seed 2.0 Pro: 3.2/16 元/百万tokens (≤32k)
        'openai': {'input': 0.01, 'output': 0.03},      # GPT-4o pricing
        'gemini': {'input': 0.0007, 'output': 0.002},
    }
    
    def __init__(self):
        self.knowledge_service = KnowledgeService(
            threshold=getattr(settings, 'KB_SIMILARITY_THRESHOLD', 0.7)
        )
        self.cache_ttl = getattr(settings, 'AI_REPLY_CACHE_TTL', 86400)
        self.keyword_filter = KeywordFilterService()
        self.scenario_monitor = ScenarioMonitorService()
        self._current_shop = None  # Track current shop for token usage recording
    
    def _normalize_model_name(self, model_version: str) -> str:
        """Normalize model version to platform name for pricing lookup."""
        model_lower = (model_version or '').lower()
        if 'deepseek' in model_lower:
            return 'deepseek'
        elif 'qwen' in model_lower:
            # Return specific qwen model for accurate pricing
            if 'turbo' in model_lower:
                return 'qwen-turbo'
            elif 'plus' in model_lower:
                return 'qwen-plus'
            elif 'max' in model_lower:
                return 'qwen-max'
            elif 'flash' in model_lower:
                return 'qwen-flash'
            return 'qwen'  # default to qwen-turbo pricing
        elif 'doubao' in model_lower:
            return 'doubao'
        elif 'gpt' in model_lower or 'openai' in model_lower:
            return 'openai'
        elif 'gemini' in model_lower:
            return 'gemini'
        return 'deepseek'  # default
    
    def _save_token_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        model_version: str,
        request_type: str = 'chat',
        shop=None,
        conversation_record=None
    ):
        """Save token usage record to database."""
        try:
            from .models import TokenUsage
            from decimal import Decimal
            
            model_name = self._normalize_model_name(model_version)
            
            # Calculate cost estimate with separate input/output pricing
            pricing = self.TOKEN_PRICING.get(model_name, {'input': 0.002, 'output': 0.003})
            input_cost = Decimal(str(prompt_tokens * pricing['input'] / 1000))
            output_cost = Decimal(str(completion_tokens * pricing['output'] / 1000))
            cost = input_cost + output_cost
            
            TokenUsage.objects.create(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model_name=model_name,
                model_version=model_version or '',
                request_type=request_type,
                cost_estimate=cost,
                shop=shop or self._current_shop,
                conversation_record=conversation_record
            )
            logger.debug(f"[Token] Saved usage: {total_tokens} tokens ({model_name})")
        except Exception as e:
            logger.warning(f"[Token] Failed to save usage: {e}")
    
    def identify_intent(self, message: str) -> Dict[str, Any]:
        """
        Identify the intent and keywords from a message.
        """
        text = (message or "").strip()
        
        keyword_categories = {
            'product': ['商品', '产品', '款式', '颜色', '尺寸', '尺码', '型号', '规格', '材质'],
            'logistics': ['物流', '快递', '发货', '配送', '运费', '到货', '几天到', '什么时候发'],
            'refund': ['退款', '退钱', '退回'],
            'return': ['退货', '换货', '退换', '寄回'],
            'invoice': ['发票', '开票', '收据'],
            'after_sales': ['售后', '维修', '保修', '投诉', '质量问题', '坏了', '损坏'],
            'discount': ['优惠', '打折', '券', '促销', '便宜', '包邮', '满减'],
            'address': ['地址', '收货人', '改地址', '收件人'],
            'order': ['订单', '下单', '付款', '支付', '拍下'],
            'price': ['价格', '多少钱', '价钱', '贵', '最低'],
        }
        
        found_keywords = []
        text_lower = text.lower()
        for category, words in keyword_categories.items():
            for word in words:
                if word in text_lower:
                    found_keywords.append(category)
                    break
        
        return {
            'type': 'customer_inquiry',
            'keywords': list(set(found_keywords)),
            'original_text': text,
        }
    
    def _is_repeated_question(self, question: str, context: str) -> bool:
        """
        Check if the current question has already been asked in the conversation context.
        Returns True if a similar question was found in the context history.
        """
        if not context:
            return False
        
        question_lower = question.strip().lower()
        # Extract buyer messages from context
        for line in context.split('\n'):
            line = line.strip()
            if line.startswith('买家:') or line.startswith('买家：'):
                prev_question = line.split(':', 1)[-1].split('：', 1)[-1].strip().lower()
                # Exact or near-exact match
                if prev_question == question_lower:
                    return True
                # High overlap check (short questions)
                if len(question_lower) > 2 and len(prev_question) > 2:
                    if question_lower in prev_question or prev_question in question_lower:
                        return True
        return False

    def generate_reply(
        self,
        question: str,
        context: str = None,
        order_detail: Dict = None,
        shop_id: str = None,
        owner_id: int = None,
        model: str = None,
        product_names: List[str] = None,
        product_card_ids: List[str] = None,
        platform: str = None,
        buyer_image_urls: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a reply using knowledge-base-first strategy.
        
        Returns:
            dict with keys: reply, source, confidence, cached
        """
        question = (question or "").strip()
        if not question:
            return {
                'reply': '您好！请问有什么可以帮到您？',
                'source': 'template',
                'confidence': 1.0,
                'cached': False,
            }
        
        platform = platform or ''
        
        # Set current shop for token usage tracking
        if shop_id:
            try:
                from apps.shops.models import Shop
                self._current_shop = Shop.objects.filter(shop_id=shop_id).first()
            except Exception as e:
                logger.warning(f"[Token] Failed to get shop: {e}")
                self._current_shop = None
        else:
            self._current_shop = None
        
        # === Step 0: Scenario monitoring check ===
        scenario_result = None
        try:
            scenario_result = self.scenario_monitor.evaluate(
                question, context, shop_id, platform, owner_id
            )
            if scenario_result and scenario_result.get('triggered'):
                action = scenario_result.get('action', 'notify_only')
                
                if action == 'no_auto_reply':
                    # Don't auto-reply, just return scenario info
                    return {
                        'reply': None,
                        'source': 'scenario_blocked',
                        'confidence': 1.0,
                        'cached': False,
                        'scenario': scenario_result,
                    }
                elif action == 'send_reply':
                    # Send a specific reply template
                    reply_template = scenario_result.get('action_config', {}).get('reply_template', '')
                    if reply_template:
                        return {
                            'reply': reply_template,
                            'source': 'scenario_reply',
                            'confidence': 1.0,
                            'cached': False,
                            'scenario': scenario_result,
                        }
                # For 'transfer_human' and 'notify_only', continue normal flow
                # but attach scenario info to the final result
        except Exception as e:
            logger.error(f"[ScenarioMonitor] Evaluation error: {e}")
        
        # === Step 1: Keyword trigger check ===
        try:
            keyword_result = self.keyword_filter.check_keyword_trigger(
                question, shop_id, platform, owner_id
            )
            if keyword_result:
                result = keyword_result
                # Attach scenario info if present
                if scenario_result and scenario_result.get('triggered'):
                    result['scenario'] = scenario_result
                return result
        except Exception as e:
            logger.error(f"[KeywordTrigger] Check error: {e}")
        
        # Detect if buyer is asking the same question again
        is_repeated = self._is_repeated_question(question, context)
        
        if is_repeated:
            # For repeated questions, skip cache and KB, call LLM directly
            # so it can see the context and vary the response
            logger.info(f"Detected repeated question, calling LLM for varied response: {question[:50]}")
            try:
                reply = self._call_openai(question, context, order_detail, varied=True, model=model, buyer_image_urls=buyer_image_urls)
                if reply:
                    return {
                        'reply': reply,
                        'source': 'openai',
                        'confidence': 0.85,
                        'cached': False,
                    }
            except Exception as e:
                logger.error(f"LLM varied reply error: {e}")
            # Fall through to normal flow if LLM fails
        
        # Step 1: Match product names to product_ids for product-specific KB search
        matched_product_ids = []
        if shop_id:
            from apps.products.models import Product
            import re
            
            # 1a. Extract product IDs from message URLs (1688/taobao/tmall links)
            url_patterns = [
                r'offer/(\d+)',           # 1688: offer/123456
                r'item\.htm\?.*?id=(\d+)', # taobao/tmall: item.htm?id=123456
                r'detail\.1688\.com/offer/(\d+)',  # 1688 detail
                r'goods_id[=:](\d+)',      # goods_id parameter
                r'item_id[=:](\d+)',       # item_id parameter
            ]
            for pattern in url_patterns:
                matches = re.findall(pattern, question)
                if matches:
                    for item_id in matches:
                        # Try to find product by platform_product_id
                        matched = Product.objects.filter(
                            shop_id=shop_id, status='active',
                            platform_product_id=item_id
                        ).values_list('product_id', flat=True)[:1]
                        matched_product_ids.extend(matched)
                        if matched:
                            logger.info(f"[ProductMatch] Matched product by URL item_id: {item_id}")
            
            # 1a2. Match from product card IDs (extracted from chat cards by frontend)
            if product_card_ids:
                for card_id in product_card_ids[:5]:
                    matched = Product.objects.filter(
                        shop_id=shop_id, status='active',
                        platform_product_id=card_id
                    ).values_list('product_id', flat=True)[:1]
                    matched_product_ids.extend(matched)
                    if matched:
                        logger.info(f"[ProductMatch] Matched product by card ID: {card_id}")
            
            # 1b. Match from order panel product names (from client)
            if product_names:
                for name in product_names[:5]:
                    matched = Product.objects.filter(
                        shop_id=shop_id, status='active',
                        name__icontains=name[:20]
                    ).values_list('product_id', flat=True)[:3]
                    matched_product_ids.extend(matched)
            
            # 1c. Smart match: analyze buyer's message against all shop products
            if not matched_product_ids:
                shop_products = list(Product.objects.filter(
                    shop_id=shop_id, status='active'
                ).values('product_id', 'name', 'platform_product_id')[:200])
                
                if shop_products:
                    q_lower = question.lower()
                    best_score = 0
                    best_pid = None
                    
                    for p in shop_products:
                        pname = (p['name'] or '').lower()
                        ppid = p['platform_product_id'] or ''
                        score = 0
                        
                        # Exact platform product ID match in message
                        if ppid and ppid in question:
                            score = 1.0
                        else:
                            # Tokenize product name: split by common delimiters
                            tokens = [t for t in re.split(r'[\s/\-\+\(\)（）【】\[\]]+', pname) if len(t) >= 2]
                            if tokens:
                                matched_tokens = sum(1 for t in tokens if t in q_lower)
                                score = matched_tokens / len(tokens)
                        
                        if score > best_score:
                            best_score = score
                            best_pid = p['product_id']
                    
                    # Lower threshold to 20% for better matching
                    if best_score >= 0.2 and best_pid:
                        matched_product_ids.append(best_pid)
                        logger.info(f"[ProductMatch] Smart matched product '{best_pid}' from message with score {best_score:.2f}")
            
            matched_product_ids = list(set(matched_product_ids))
            if matched_product_ids:
                logger.info(f"[ProductMatch] Final matched {len(matched_product_ids)} products: {matched_product_ids}")
        
        kb_matches = self.knowledge_service.search_similar(
            question, shop_id=shop_id, owner_id=owner_id, product_ids=matched_product_ids, limit=3
        )
        
        kb_reference = None
        if kb_matches:
            for r in kb_matches:
                if r.get('is_correct'):
                    kb_reference = r
                    break
            
            if kb_reference:
                from apps.knowledge.models import KnowledgeBase
                KnowledgeBase.objects.filter(id=kb_reference['id']).update(usage_count=F('usage_count') + 1)
                logger.info(
                    f"[KB] Found reference answer (similarity={kb_reference.get('similarity', 0):.2f}): "
                    f"{(kb_reference.get('answer') or '')[:50]}..."
                )
        
        # Step 3: Call LLM API with product knowledge context and KB reference
        # Log which model is being used
        if model:
            logger.info(f"[模型调用] 前端指定模型: '{model}'")
        
        # Build contexts for LLM
        conversation_context = context or ''
        knowledge_parts: List[str] = []
        source_map = {
            'manual': '手动录入',
            'auto_learned': '自动学习',
            'ai_generated': 'AI生成',
        }
        if matched_product_ids and shop_id:
            from apps.knowledge.models import KnowledgeBase
            product_qa_items = KnowledgeBase.objects.filter(
                product_id__in=matched_product_ids, shop_id=shop_id
            ).values('question', 'answer', 'is_correct', 'source')[:15]
            if product_qa_items:
                qa_text = '\n'.join([
                    f"问: {item.get('question', '')}\n"
                    f"答: {item.get('answer', '')}\n"
                    f"(来源: {source_map.get(item.get('source'), item.get('source'))}, 已确认: {'是' if item.get('is_correct') else '否'})"
                    for item in product_qa_items
                ])
                knowledge_parts.append(f"【该商品的知识库参考】\n{qa_text}")
        
        if kb_reference:
            kb_hint = (
                "【参考答案】\n"
                f"问: {kb_reference.get('question', '')}\n"
                f"答: {kb_reference.get('answer', '')}\n"
                f"(来源: {source_map.get(kb_reference.get('source'), kb_reference.get('source'))}, 已确认: {'是' if kb_reference.get('is_correct') else '否'}, 相似度: {kb_reference.get('similarity', 0):.2f})"
            )
            knowledge_parts.append(kb_hint)
        elif kb_matches:
            cand_lines = []
            for i, r in enumerate(kb_matches[:3], start=1):
                cand_lines.append(
                    f"{i}. (来源: {source_map.get(r.get('source'), r.get('source'))}, 已确认: {'是' if r.get('is_correct') else '否'}, 相似度: {r.get('similarity', 0):.2f})\n"
                    f"问: {r.get('question','')}\n"
                    f"答: {r.get('answer','')}"
                )
            knowledge_parts.append("【知识库相似问答】\n" + "\n".join(cand_lines))
        
        combined_context = ""
        if conversation_context:
            combined_context = f"【对话历史】\n{conversation_context}"
        if knowledge_parts:
            knowledge_context = "\n\n".join(knowledge_parts)
            combined_context = f"{combined_context}\n\n【知识库资料】\n{knowledge_context}" if combined_context else f"【知识库资料】\n{knowledge_context}"
        
        if not context and not knowledge_parts:
            cache_key = f"ai_reply:{md5_hash(question)}"
            cached_reply = cache.get(cache_key)
            if cached_reply:
                return {
                    'reply': cached_reply,
                    'source': 'cache',
                    'confidence': 0.9,
                    'cached': True,
                }
        
        try:
            # _call_openai now handles model fallback automatically
            reply = self._call_openai(question, combined_context, order_detail, model=model, buyer_image_urls=buyer_image_urls)
            
            if reply:
                from apps.knowledge.models import KnowledgeBase
                # Only save to KB if no reference was used (to avoid duplicates)
                if not kb_reference:
                    from apps.knowledge.utils import infer_shop_id
                    resolved_shop_id = infer_shop_id(owner_id=owner_id, shop_id=shop_id)
                    KnowledgeBase.objects.create(
                        question=question,
                        answer=reply,
                        is_correct=False,
                        source='ai_generated',
                        shop_id=resolved_shop_id,
                        owner_id=owner_id,
                    )
                
                if not context:
                    cache_key = f"ai_reply:{md5_hash(question)}"
                    cache.set(cache_key, reply, self.cache_ttl)
                
                # Check which model was actually used (primary or fallback)
                actual_model = self._get_available_model(model)
                using_fallback = actual_model != model if model else False
                
                result = {
                    'reply': reply,
                    'source': 'ai_kb' if knowledge_parts else 'openai',
                    'confidence': 0.9 if kb_reference else (0.86 if knowledge_parts else 0.85),
                    'cached': False,
                    'model_used': actual_model or 'default',
                }
                
                if kb_reference:
                    result['kb_id'] = kb_reference['id']
                    result['kb_enhanced'] = True
                    if kb_reference.get('source') and kb_reference.get('source') != 'manual':
                        result['needs_verification'] = True
                
                if using_fallback:
                    result['model_fallback'] = True
                    result['original_model'] = model
                    result['fallback_model'] = actual_model
                
                return result
        except Exception as e:
            logger.error(f"LLM API error: {e}")
        
        # Step 5: Fallback to template (only if all models failed)
        reply = self._generate_template_reply(question, order_detail)
        
        result = {
            'reply': reply,
            'source': 'template',
            'confidence': 0.5,
            'cached': False,
        }
        
        # All models were unavailable
        if model:
            result['model_unavailable'] = True
            result['model_error'] = f"所有模型均不可用（主模型: {model}），已使用模板回复"
        
        return self._postprocess_reply(result, shop_id, platform, owner_id, scenario_result)
    
    def _postprocess_reply(self, result, shop_id, platform, owner_id, scenario_result=None):
        """Apply sensitive word filtering and attach scenario info to result."""
        # Sensitive word filtering
        if result.get('reply') and result.get('source') != 'keyword_trigger':
            try:
                result['reply'] = self.keyword_filter.filter_sensitive_words(
                    result['reply'], shop_id, platform or '', owner_id
                )
            except Exception as e:
                logger.error(f"[SensitiveFilter] Error: {e}")
        
        # Attach scenario info if present
        if scenario_result and scenario_result.get('triggered'):
            result['scenario'] = scenario_result
        
        return result
    
    # Model configurations mapping frontend model names to API settings
    MODEL_CONFIGS = {
        'doubao-seed-2.0-pro': {
            'provider': 'doubao',
            'api_key_setting': 'DOUBAO_API_KEY',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'model': 'doubao-seed-2-0-pro-260215',
        },
        'doubao-seed-1.6': {
            'provider': 'doubao',
            'api_key_setting': 'DOUBAO_API_KEY',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'model': 'doubao-seed-2-0-pro-260215',
        },
        'deepseek-v3.2': {
            'provider': 'deepseek',
            'api_key_setting': 'DEEPSEEK_API_KEY',
            'base_url': 'https://api.deepseek.com/v1',
            'model': 'deepseek-chat',
        },
        'gemini-3.0-pro': {
            'provider': 'gemini',
            'api_key_setting': 'GEMINI_API_KEY',
            'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
            'model': 'gemini-2.0-flash',
        },
        'gpt-5': {
            'provider': 'openai',
            'api_key_setting': 'OPENAI_API_KEY',
            'base_url': 'https://api.openai.com/v1',
            'model': 'gpt-4o',
        },
        'qwen-3-plus': {
            'provider': 'qwen',
            'api_key_setting': 'QWEN_API_KEY',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'model': 'qwen-plus',
        },
        'gpt-4o-mini': {
            'provider': 'openai',
            'api_key_setting': 'OPENAI_API_KEY',
            'base_url': 'https://api.openai.com/v1',
            'model': 'gpt-4o-mini',
        },
        # Vision Language Models (VLM) - 视觉语言模型
        'qwen-vl-plus': {
            'provider': 'qwen',
            'api_key_setting': 'QWEN_API_KEY',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'model': 'qwen-vl-plus',
            'is_vision': True,
        },
        'qwen-vl-max': {
            'provider': 'qwen',
            'api_key_setting': 'QWEN_API_KEY',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'model': 'qwen-vl-max',
            'is_vision': True,
        },
        'doubao-vision': {
            'provider': 'doubao',
            'api_key_setting': 'DOUBAO_API_KEY',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'model': 'doubao-seed-2-0-pro-260215',
            'is_vision': True,
        },
    }
    
    # Fallback model priority order (used when primary model is unavailable)
    FALLBACK_MODEL_PRIORITY = [
        'deepseek-v3.2',    # DeepSeek as first fallback (cost-effective)
        'doubao-seed-2.0-pro',  # Doubao as second fallback (text priority 2)
        'qwen-3-plus',       # Qwen as third fallback
        'gpt-4o-mini',       # GPT as fourth fallback
        'gemini-3.0-pro',    # Gemini as fifth fallback
    ]
    
    def _get_api_key(self, setting_name: str) -> str:
        """
        Get API key from database first, fallback to environment variable.
        This allows users to configure API keys via web UI without restarting.
        """
        # Try database first
        db_key = self.API_KEY_DB_MAPPING.get(setting_name)
        if db_key:
            try:
                from apps.accounts.models import SystemSettings
                setting = SystemSettings.objects.filter(key=db_key).first()
                if setting and setting.value and setting.value.strip():
                    return setting.value.strip()
            except Exception as e:
                logger.debug(f"[API Key] 从数据库获取 {db_key} 失败: {e}")
        
        # Fallback to environment variable via Django settings
        api_key = getattr(settings, setting_name, '')
        return api_key if api_key else ''
    
    def _check_model_health(self, model: str) -> bool:
        """
        Check if a model is healthy (has API key configured and can respond).
        Results are cached for MODEL_HEALTH_TTL seconds.
        """
        if not model or model not in self.MODEL_CONFIGS:
            return False
        
        cache_key = f"{MODEL_HEALTH_CACHE_PREFIX}{model}"
        cached_health = cache.get(cache_key)
        
        if cached_health is not None:
            return cached_health
        
        # Check if API key is configured
        model_config = self.MODEL_CONFIGS[model]
        api_key = self._get_api_key(model_config['api_key_setting'])
        
        if not api_key:
            logger.info(f"[模型健康检查] {model}: API Key 未配置")
            cache.set(cache_key, False, MODEL_HEALTH_TTL)
            return False
        
        # Try a simple API call to verify the model works
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=model_config['base_url'],
                timeout=10  # Short timeout for health check
            )
            
            response = client.chat.completions.create(
                model=model_config['model'],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            
            if response and response.choices:
                logger.info(f"[模型健康检查] {model}: 健康 ✓")
                cache.set(cache_key, True, MODEL_HEALTH_TTL)
                return True
        except Exception as e:
            logger.warning(f"[模型健康检查] {model}: 不可用 - {str(e)[:100]}")
        
        cache.set(cache_key, False, MODEL_HEALTH_TTL)
        return False
    
    def _get_available_model(self, primary_model: str) -> Optional[str]:
        """
        Get an available model, trying primary first then fallbacks.
        Returns the model name if available, None if all models are unavailable.
        """
        # Try primary model first
        if primary_model:
            if self._check_model_health(primary_model):
                return primary_model
            logger.warning(f"[模型降级] 主模型 '{primary_model}' 不可用，尝试备用模型...")
        
        # Try fallback models in order
        for fallback_model in self.FALLBACK_MODEL_PRIORITY:
            if fallback_model == primary_model:
                continue  # Skip if same as primary
            if self._check_model_health(fallback_model):
                logger.info(f"[模型降级] 切换到备用模型: {fallback_model}")
                return fallback_model
        
        logger.error("[模型降级] 所有模型均不可用！")
        return None
    
    def _invalidate_model_health_cache(self, model: str = None):
        """Invalidate health cache for a specific model or all models."""
        if model:
            cache.delete(f"{MODEL_HEALTH_CACHE_PREFIX}{model}")
        else:
            for m in self.MODEL_CONFIGS.keys():
                cache.delete(f"{MODEL_HEALTH_CACHE_PREFIX}{m}")
    
    def _get_llm_config(self, model: str = None) -> Dict[str, Any]:
        """Get LLM configuration based on model selection or provider setting."""
        
        # If a specific model is selected, use its configuration
        if model and model in self.MODEL_CONFIGS:
            model_config = self.MODEL_CONFIGS[model]
            api_key = self._get_api_key(model_config['api_key_setting'])
            
            config = {
                'provider': model_config['provider'],
                'api_key': api_key,
                'base_url': model_config['base_url'],
                'model': model_config['model'],
                'temperature': getattr(settings, 'LLM_TEMPERATURE', 0.3),
            }
            logger.info(f"Using selected model: {model} -> {model_config['model']}")
            return config
        
        # Fall back to environment-based provider setting
        provider = getattr(settings, 'LLM_PROVIDER', 'deepseek').lower()
        
        configs = {
            'deepseek': {
                'api_key': getattr(settings, 'DEEPSEEK_API_KEY', ''),
                'base_url': getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1'),
                'model': getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat'),
            },
            'openai': {
                'api_key': getattr(settings, 'OPENAI_API_KEY', ''),
                'base_url': getattr(settings, 'OPENAI_BASE_URL', 'https://api.openai.com/v1'),
                'model': getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
            },
            'qwen': {
                'api_key': getattr(settings, 'QWEN_API_KEY', ''),
                'base_url': getattr(settings, 'QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                'model': getattr(settings, 'QWEN_MODEL', 'qwen-turbo'),
            },
            'doubao': {
                'api_key': getattr(settings, 'DOUBAO_API_KEY', ''),
                'base_url': getattr(settings, 'DOUBAO_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3'),
                'model': getattr(settings, 'DOUBAO_MODEL', 'doubao-seed-2-0-pro-260215'),
            },
            'gemini': {
                'api_key': getattr(settings, 'GEMINI_API_KEY', ''),
                'base_url': getattr(settings, 'GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/'),
                'model': getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash'),
            },
        }
        
        config = configs.get(provider, configs['deepseek'])
        config['provider'] = provider
        config['temperature'] = getattr(settings, 'LLM_TEMPERATURE', 0.3)
        return config
    
    def _call_llm(
        self, 
        question: str, 
        context: str = None,
        order_detail: Dict = None,
        varied: bool = False,
        model: str = None,
        buyer_image_urls: List[str] = None
    ) -> Optional[str]:
        """
        Call LLM API to generate a reply with automatic fallback to backup models.
        Supports DeepSeek, OpenAI, Qwen, Doubao, Gemini, etc.
        
        Enhanced with:
        - Multi-turn message parsing for better context understanding
        - Multimodal image support for Doubao-Seed-2.0-pro
        """
        # Default to DeepSeek for text conversations when no model specified
        if not model:
            model = 'deepseek-v3.2'
            logger.info(f"[模型调用] 未指定模型，默认使用 DeepSeek")
        
        # Get an available model (primary or fallback)
        primary_model = model
        available_model = self._get_available_model(primary_model)
        
        if not available_model:
            logger.error("[模型调用] 没有可用的模型，无法生成回复")
            return None
        
        # Track if we're using a fallback model
        using_fallback = available_model != primary_model if primary_model else False
        if using_fallback:
            logger.info(f"[模型降级] 使用备用模型 '{available_model}' 替代 '{primary_model}'")
        
        config = self._get_llm_config(model=available_model)
        api_key = config['api_key']
        
        if not api_key:
            # This shouldn't happen since _get_available_model checks health
            logger.error(f"[模型调用] 模型 '{available_model}' 配置异常")
            return None
        
        try:
            from openai import OpenAI
            
            client = OpenAI(
                api_key=api_key,
                base_url=config['base_url']
            )
            
            system_prompt = (
                "你是一位专业热情的电商客服助手。请用中文回复客户。\n"
                "回复要求：\n"
                "1. 仔细理解买家的问题意图，结合对话历史给出有针对性的回答（优先以最近一两条买家消息为主）\n"
                "2. 如果买家只发送了商品链接或商品卡片，没有提出具体问题，请主动询问需求：'亲，在的，请问您对这款商品有什么想了解的呢？'\n"
                "3. 如果提供了【知识库资料】或【参考答案】，优先使用其中明确陈述的信息来回答；不匹配当前问题则忽略，自己组织回答\n"
                "4. 如果知识库资料标注为“自动学习/AI生成”且“未确认”，只把它当作可能线索；不确定就追问1个关键点再回答\n"
                "5. 如果买家询问产品是否适合某种用途，且知识库/图片分析中有明确相关信息，据实回答；如果没有相关资料，诚实说'这个我帮您确认一下哈'，不要根据常识猜测\n"
                "6. 只有涉及精确数值参数（价格、库存、电压、功率等）且你不确定时，才引导查看详情页\n"
                "7. 使用亲切自然的语气，像真人客服一样交流\n"
                "8. 回复控制在80字以内，必要时可两句话，不要太生硬\n"
                "9. 如果买家表达不满或抱怨，先表示理解和歉意，再尝试解决问题\n"
                "10. 如果买家重复提问，换种表达方式回答\n"
                "11. 如果提供了订单信息，结合订单状态回答\n"
                "12. 禁止编造具体数值参数，不确定的数值说'建议您确认一下详情页哦'\n"
                "13. 禁止说'正在查询'、'请稍等'这类无意义的话，要么直接回答问题，要么询问买家需求\n"
                "14. 严禁杜撰产品功能或技术规格！你不知道的信息绝对不能编造。如果买家提供了图片证据（如商品详情页截图）说明产品支持某功能，你必须尊重图片中的事实，不得否认或编造理由反驳\n"
                "15. 如果买家发送了图片且【买家发送的图片内容】中有明确信息，以图片实际内容为准回答，不要与图片内容矛盾\n"
                "16. 当你的知识库信息与买家提供的店铺图片/描述冲突时，优先信任店铺图片和描述的实际内容，承认可能存在信息差异并协助核实\n"
                "17. 【极重要】你没有发送图片、文件、截图、报告的能力！严禁声称'已发送图片'、'截图已上传'、'图片发至窗口'等虚假承诺。如果买家需要图片或文件资料，正确做法是：告知'亲，我这边无法直接发送图片文件，您可以在商品详情页查看相关资料，或者联系人工客服获取哦~'\n"
                "18. 严禁在回复中虚构任何已完成的操作（如'已发送'、'已上传'、'已帮您处理'），只能描述你真正能做的事情——即文字回复买家问题\n"
                "19. 【物流承诺禁令】严禁承诺具体的发货时间或快递公司！不得说'今天发'、'明天发'、'发顺丰'、'发京东'等，除非知识库中有店铺的明确政策。正确回复：'亲，我们会尽快为您安排发货的，具体以实际发出为准哦~' 或 '亲，发货时间和快递以实际为准，下单后我们会尽快处理~'\n"
                "20. 【备注禁令】严禁声称'已帮您备注'、'已备注XX'，你没有备注订单的能力！如买家有特殊要求，正确回复：'亲，您的需求我已记录，下单时可以在订单备注里写明哦~' 或 '亲，建议您下单时在备注栏注明，仓库会按备注处理~'\n"
                "21. 【拼多多运费险规则】严禁使用'运费险'这个词！拼多多平台没有运费险，只有'退货包运费'服务。如果买家询问运费险相关问题，回复时用'退货包运费'代替。是否有退货包运费服务必须根据知识库中该店铺的实际政策回答，不能凭空编造。如果知识库没有相关信息，回复：'亲，关于退货包运费的问题，建议您查看商品详情页或咨询人工客服确认哦~'\n"
                "22. 【保修规则】禁止主动承诺1年保修！关于保修问题，首先引导买家查看商品详情页的保修说明。如果买家反复询问保修问题超过2次，则回复：'亲，本产品保修3个月哦~'"
            )
            
            # Increase temperature for varied responses
            temperature = config['temperature']
            if varied:
                temperature = min(temperature + 0.3, 0.9)
            
            messages = [{"role": "system", "content": system_prompt}]
            
            if context:
                import re
                conv_text = None
                kb_text = None
                image_analysis_text = None
                video_analysis_text = None
                
                m_conv = re.search(r'【对话历史】\n([\s\S]*?)(?=\n\n【知识库资料】\n|\n\n【买家发送的图片内容】\n|\n\n【买家发送的视频内容】\n|$)', context)
                if m_conv:
                    conv_text = (m_conv.group(1) or '').strip()
                
                m_kb = re.search(r'【知识库资料】\n([\s\S]*?)(?=\n\n【买家发送的图片内容】\n|\n\n【买家发送的视频内容】\n|$)', context)
                if m_kb:
                    kb_text = (m_kb.group(1) or '').strip()
                
                m_img = re.search(r'【买家发送的图片内容】\n([\s\S]*?)(?=\n\n【买家发送的视频内容】\n|$)', context)
                if m_img:
                    image_analysis_text = (m_img.group(1) or '').strip()
                
                m_vid = re.search(r'【买家发送的视频内容】\n([\s\S]*?)$', context)
                if m_vid:
                    video_analysis_text = (m_vid.group(1) or '').strip()
                
                if not conv_text and not kb_text and not image_analysis_text and not video_analysis_text:
                    conv_text = context.strip()
                
                # Enhanced: Parse conversation history into multi-turn message format
                # Provides much better context understanding for Doubao-Seed-2.0-pro (256k context)
                if conv_text:
                    conv_lines = conv_text.split('\n')
                    turn_messages = []
                    
                    for line in conv_lines:
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith('买家:') or line.startswith('买家：'):
                            buyer_msg = re.split(r'[:：]', line, 1)[-1].strip()
                            if buyer_msg:
                                turn_messages.append({"role": "user", "content": buyer_msg})
                        elif line.startswith('客服:') or line.startswith('客服：'):
                            agent_msg = re.split(r'[:：]', line, 1)[-1].strip()
                            if agent_msg:
                                turn_messages.append({"role": "assistant", "content": agent_msg})
                    
                    if len(turn_messages) >= 2:
                        # Multi-turn format: insert history as real user/assistant turns
                        recent_turns = turn_messages[-8:]
                        # Remove last message if it duplicates the current question
                        if recent_turns and recent_turns[-1]['role'] == 'user':
                            last_msg = recent_turns[-1]['content'].strip()
                            if last_msg == question.strip() or question.strip().startswith(last_msg):
                                recent_turns = recent_turns[:-1]
                        
                        if recent_turns:
                            messages.append({
                                "role": "system",
                                "content": "以下是与买家的对话历史，请结合上下文理解买家当前的意图和需求："
                            })
                            messages.extend(recent_turns)
                            logger.info(f"[上下文] 多轮消息格式，共{len(recent_turns)}条历史")
                    else:
                        # Fallback: single system message for unstructured context
                        messages.append({
                            "role": "system",
                            "content": f"以下是与买家的对话历史（仅用于理解上下文）：\n{conv_text}"
                        })
                
                if kb_text:
                    messages.append({
                        "role": "system",
                        "content": "以下是店铺/商品知识库资料（可作为事实依据；请融合进回复，不要对外提及“知识库”）：\n" + kb_text
                    })
                
                # Include image/video analysis text for richer understanding
                if image_analysis_text:
                    messages.append({
                        "role": "system",
                        "content": f"以下是对买家发送图片的AI分析结果，请结合此信息回答：\n{image_analysis_text}"
                    })
                
                if video_analysis_text:
                    messages.append({
                        "role": "system",
                        "content": f"以下是对买家发送视频的AI分析结果，请结合此信息回答：\n{video_analysis_text}"
                    })
            
            if varied:
                messages.append({
                    "role": "system",
                    "content": "注意：买家正在重复提问相同的问题，你之前已经回答过了（见对话历史）。请务必用不同的措辞和句式重新回答，意思一样但表达方式要明显不同，不要复制之前的回复。"
                })
            
            if order_detail:
                order_lines = []
                
                # Handle new structured format from DOM extraction
                for order in order_detail.get('orders', []):
                    if order.get('orderId'):
                        order_lines.append(f"订单号: {order['orderId']}")
                    if order.get('paymentStatus'):
                        order_lines.append(f"支付状态: {order['paymentStatus']}")
                    if order.get('shippingStatus'):
                        order_lines.append(f"物流状态: {order['shippingStatus']}")
                    for p in order.get('products', []):
                        line = f"商品: {p.get('name', '未知')}"
                        if p.get('specs'):
                            line += f" ({p['specs']})"
                        if p.get('price'):
                            line += f" 价格:{p['price']}"
                        order_lines.append(line)
                
                # Backward compatible: handle old format {order_id, products[{name}]}
                if not order_lines and order_detail.get('order_id'):
                    order_lines.append(f"订单号: {order_detail['order_id']}")
                    if 'products' in order_detail:
                        for p in order_detail.get('products', []):
                            if p.get('name'):
                                order_lines.append(f"商品: {p['name']}")
                
                if order_lines:
                    order_context = "\n".join(order_lines)
                    messages.append({
                        "role": "system",
                        "content": f"当前买家的订单信息：\n{order_context}\n请根据订单实际状态回答买家问题。"
                    })
                
                # Chat images info
                chat_images = order_detail.get('chatImages', [])
                if chat_images:
                    messages.append({
                        "role": "system",
                        "content": f"买家在聊天中发送了{len(chat_images)}张图片，请结合图片内容和上下文回答。"
                    })
            
            # Build final user message - support multimodal images for Doubao-Seed-2.0-pro
            # When buyer_image_urls are provided and model supports vision, include images directly
            model_config = self.MODEL_CONFIGS.get(available_model, {})
            is_doubao_model = model_config.get('provider') == 'doubao'
            
            if buyer_image_urls and is_doubao_model:
                # Multimodal: send images + text together for Doubao's unified understanding
                user_content = []
                for img_url in buyer_image_urls[:3]:  # Limit to 3 images
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url}
                    })
                user_content.append({
                    "type": "text",
                    "text": question
                })
                messages.append({
                    "role": "user",
                    "content": user_content
                })
                logger.info(f"[多模态] 使用 Doubao 多模态，图片{len(buyer_image_urls[:3])}张 + 文字问题")
            else:
                messages.append({
                    "role": "user",
                    "content": question
                })
            
            response = client.chat.completions.create(
                model=config['model'],
                temperature=temperature,
                messages=messages,
                max_tokens=260,
            )
            
            if response and response.choices:
                reply = response.choices[0].message.content.strip()
                
                # Save token usage
                if hasattr(response, 'usage') and response.usage:
                    self._save_token_usage(
                        prompt_tokens=response.usage.prompt_tokens or 0,
                        completion_tokens=response.usage.completion_tokens or 0,
                        total_tokens=response.usage.total_tokens or 0,
                        model_version=config['model'],
                        request_type='chat'
                    )
                
                logger.info(f"LLM [{config['provider']}] reply: {reply[:50]}...")
                return reply
            
        except Exception as e:
            logger.error(f"LLM API call failed [{config['provider']}]: {e}")
        
        return None
    
    def _call_openai(
        self, 
        question: str, 
        context: str = None,
        order_detail: Dict = None,
        varied: bool = False,
        model: str = None,
        buyer_image_urls: List[str] = None
    ) -> Optional[str]:
        """Legacy method - redirects to _call_llm for backward compatibility."""
        return self._call_llm(question, context, order_detail, varied=varied, model=model, buyer_image_urls=buyer_image_urls)
    
    def call_vision_model(
        self,
        prompt: str,
        image_base64: str,
        model: str = 'doubao-vision'
    ) -> Dict[str, Any]:
        """
        Call vision language model to analyze an image.
        Automatically falls back to alternative vision models if primary fails.
        
        Args:
            prompt: The instruction/question for the vision model
            image_base64: Base64 encoded image data (without data:image prefix)
            model: Vision model to use (default: doubao-vision, priority 1)
        
        Returns:
            dict with keys: success, content, error, model_used
        """
        # Vision model fallback order: Doubao priority 1
        vision_models = ['doubao-vision', 'qwen-vl-plus', 'qwen-vl-max']
        
        # Debug: Log API key status
        logger.info(f"[视觉模型] 检查API Key配置...")
        logger.info(f"[视觉模型] QWEN_API_KEY: {'已配置' if getattr(settings, 'QWEN_API_KEY', '') else '未配置'}")
        logger.info(f"[视觉模型] DOUBAO_API_KEY: {'已配置' if getattr(settings, 'DOUBAO_API_KEY', '') else '未配置'}")
        
        # If specified model is in list, start from there
        if model in vision_models:
            start_idx = vision_models.index(model)
            vision_models = vision_models[start_idx:] + vision_models[:start_idx]
        
        last_error = None
        
        for vm in vision_models:
            if vm not in self.MODEL_CONFIGS:
                logger.info(f"[视觉模型] {vm} 不在MODEL_CONFIGS中，跳过")
                continue
                
            model_config = self.MODEL_CONFIGS[vm]
            
            # Verify this is a vision model
            if not model_config.get('is_vision'):
                continue
            
            api_key = self._get_api_key(model_config['api_key_setting'])
            
            if not api_key:
                logger.info(f"[视觉模型] {vm} 的API Key未配置 (setting: {model_config['api_key_setting']})，跳过")
                continue
            
            logger.info(f"[视觉模型] {vm} API Key已配置，长度: {len(api_key)}")
            
            try:
                from openai import OpenAI
                
                client = OpenAI(
                    api_key=api_key,
                    base_url=model_config['base_url'],
                    timeout=90  # Vision models may need more time
                )
                
                # Build message with image
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
                
                logger.info(f"[视觉模型] 尝试使用 {vm}...")
                
                response = client.chat.completions.create(
                    model=model_config['model'],
                    messages=messages,
                    max_tokens=4000,
                )
                
                if response and response.choices:
                    content = response.choices[0].message.content.strip()
                    logger.info(f"[视觉模型] {vm} 分析完成，返回 {len(content)} 字符")
                    
                    # Save token usage for vision model
                    if hasattr(response, 'usage') and response.usage:
                        self._save_token_usage(
                            prompt_tokens=response.usage.prompt_tokens or 0,
                            completion_tokens=response.usage.completion_tokens or 0,
                            total_tokens=response.usage.total_tokens or 0,
                            model_version=model_config['model'],
                            request_type='vision'
                        )
                    
                    return {
                        'success': True,
                        'content': content,
                        'error': None,
                        'model_used': vm
                    }
                else:
                    last_error = '视觉模型返回空响应'
                    logger.warning(f"[视觉模型] {vm} 返回空响应")
                    
            except Exception as e:
                error_msg = str(e)[:200]
                last_error = error_msg
                logger.warning(f"[视觉模型] {vm} 调用失败: {error_msg}，尝试下一个模型")
                continue
        
        # All models failed
        return {
            'success': False,
            'content': None,
            'error': f'所有视觉模型都失败: {last_error}',
            'model_used': None
        }
    
    def analyze_page_screenshot(
        self,
        image_base64: str,
        page_type: str = 'list',
        model: str = 'doubao-vision'
    ) -> Dict[str, Any]:
        """
        Analyze a page screenshot for AI-driven learning agent.
        
        Args:
            image_base64: Base64 encoded screenshot
            page_type: 'list' for product list page, 'detail' for product detail page
            model: Vision model to use
        
        Returns:
            dict with: success, action, data, error
            action can be: 'click', 'scroll', 'extract', 'back', 'done'
        """
        if page_type == 'list':
            prompt = """你是一个电商页面分析助手。请分析这个商品列表页面的截图。

任务：找到已勾选的商品（复选框被选中的商品），并告诉我应该点击哪个商品标题进入详情页。

请严格按照以下JSON格式返回：
{
    "page_type": "list",
    "has_checked_products": true/false,
    "action": "click" 或 "scroll" 或 "done",
    "target": {
        "description": "需要点击的商品名称或位置描述",
        "position": "top/middle/bottom",
        "product_name": "商品名称（如果能识别）"
    },
    "reason": "执行此操作的原因",
    "remaining_count": 估计还有几个已勾选的商品待处理
}

注意：
1. 如果看到已勾选的商品，action 应为 "click"，并描述点击目标
2. 如果需要滚动才能看到更多已勾选商品，action 为 "scroll"
3. 如果没有已勾选的商品或已全部处理完，action 为 "done"
4. 只返回JSON，不要有其他文字"""
        
        elif page_type == 'detail':
            prompt = """你是一个电商页面分析助手。请分析这个商品详情页面的截图。

任务：提取页面上的商品信息，包括标题、价格、规格、描述等。

请严格按照以下JSON格式返回：
{
    "page_type": "detail",
    "action": "extract" 或 "scroll" 或 "back",
    "product_info": {
        "name": "商品名称",
        "price": "价格",
        "specs": ["规格1", "规格2"],
        "description": "商品描述（前200字）",
        "features": ["特点1", "特点2"]
    },
    "need_scroll": true/false,
    "scroll_reason": "如果需要滚动，说明原因",
    "extraction_complete": true/false
}

注意：
1. 如果当前视图已包含足够的商品信息，action 为 "extract"，extraction_complete 为 true
2. 如果需要滚动查看更多信息（如商品详情图片），action 为 "scroll"
3. 如果信息提取完成，需要返回列表页，action 为 "back"
4. 尽量提取所有可见的商品信息
5. 只返回JSON，不要有其他文字"""
        
        else:
            return {
                'success': False,
                'action': None,
                'data': None,
                'error': f'未知的页面类型: {page_type}'
            }
        
        result = self.call_vision_model(prompt, image_base64, model)
        
        if not result['success']:
            return {
                'success': False,
                'action': None,
                'data': None,
                'error': result['error']
            }
        
        # Parse JSON response from vision model
        try:
            content = result['content']
            
            # Handle potential markdown code blocks
            if '```' in content:
                # Extract JSON from code block
                import re
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if json_match:
                    content = json_match.group(1)
            
            data = json.loads(content)
            action = data.get('action', 'done')
            
            return {
                'success': True,
                'action': action,
                'data': data,
                'error': None,
                'model_used': result['model_used']
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"[视觉分析] JSON解析失败: {e}, 原始内容: {result['content'][:200]}")
            return {
                'success': False,
                'action': None,
                'data': None,
                'error': f'视觉模型返回的内容不是有效JSON: {str(e)}'
            }
    
    def _generate_template_reply(
        self, 
        question: str, 
        order_detail: Dict = None
    ) -> str:
        """Generate a fallback template reply in Chinese."""
        if order_detail:
            order_id = order_detail.get('order_id', '')
            products = order_detail.get('products', [])
            if products:
                product_names = '、'.join([
                    p.get('name', '商品') for p in products[:3]
                ])
                return (
                    f"亲，关于您咨询的问题，您的订单{order_id}包含：{product_names}。"
                    f"我们会尽快为您处理，请稍等~"
                )
        
        # Check if it looks like a product link/info rather than a question
        if any(c in question for c in ['￥', '¥', 'http', '.com', '.cn']):
            return "亲，您好！请问您对这个商品有什么需要了解的呢？有任何问题都可以问我哦~"
        
        return "亲，您好！已收到您的消息，正在为您查询中，请稍等一下哦~"
    
    def extract_product_info(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use AI to extract structured product information from raw product data.
        
        Args:
            product_data: dict with keys like name, description, specs_json, price, etc.
        
        Returns:
            dict with extracted info: category, keywords, key_features, specs_summary
        """
        # Use DeepSeek for product info extraction
        config = self._get_llm_config(model='deepseek-v3.2')
        api_key = config['api_key']
        
        if not api_key:
            logger.warning(f"LLM API key not configured, using fallback extraction")
            return self._fallback_extract_product_info(product_data)
        
        try:
            from openai import OpenAI
            
            client = OpenAI(
                api_key=api_key,
                base_url=config['base_url']
            )
            
            # Build product context
            product_context = f"""
商品名称: {product_data.get('name', '未知')}
商品价格: {product_data.get('price', '未知')}
商品描述: {product_data.get('description', '无描述')}
规格信息: {json.dumps(product_data.get('specs_json', {}), ensure_ascii=False) if product_data.get('specs_json') else '无规格信息'}
"""
            
            system_prompt = """你是一个电商商品信息分析专家。请从给定的商品信息中提取关键信息。

请严格按照以下JSON格式返回，不要添加任何其他内容：
{
    "category": "商品所属类目，如：服装/数码/家居/食品等",
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "key_features": ["商品特点1", "商品特点2", "商品特点3"],
    "specs_summary": "规格参数的简要总结，50字以内"
}

注意：
1. keywords至少提取3个，最多5个
2. key_features至少提取2个，最多5个
3. 如果某些信息无法提取，使用合理的默认值
4. 只返回JSON，不要有其他文字"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": product_context}
            ]
            
            response = client.chat.completions.create(
                model=config['model'],
                temperature=0.2,
                messages=messages,
                max_tokens=500,
            )
            
            if response and response.choices:
                content = response.choices[0].message.content.strip()
                # Try to parse JSON from response
                try:
                    # Handle potential markdown code blocks
                    if content.startswith('```'):
                        content = content.split('```')[1]
                        if content.startswith('json'):
                            content = content[4:]
                    result = json.loads(content)
                    logger.info(f"Successfully extracted product info for: {product_data.get('name', '')[:30]}")
                    return result
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse AI response as JSON: {e}")
                    return self._fallback_extract_product_info(product_data)
                    
        except Exception as e:
            logger.error(f"LLM API call failed for extract_product_info: {e}")
        
        return self._fallback_extract_product_info(product_data)
    
    def _fallback_extract_product_info(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback extraction when AI is unavailable."""
        name = product_data.get('name', '')
        description = product_data.get('description', '')
        
        # Simple keyword extraction from name
        keywords = []
        if name:
            # Remove common words and split
            words = name.replace('【', ' ').replace('】', ' ').split()
            keywords = [w for w in words if len(w) >= 2][:5]
        
        return {
            "category": "未分类",
            "keywords": keywords or ["商品"],
            "key_features": [description[:50] if description else "暂无特点描述"],
            "specs_summary": "详见商品规格"
        }
    
    def generate_product_qa(
        self, 
        product_data: Dict[str, Any], 
        extracted_info: Dict[str, Any] = None
    ) -> List[Dict[str, str]]:
        """
        Use AI to generate Q&A pairs for a product.
        
        Args:
            product_data: dict with product details
            extracted_info: optional pre-extracted product info
        
        Returns:
            List of dicts, each with 'question' and 'answer' keys
        """
        # Use DeepSeek for Q&A generation
        config = self._get_llm_config(model='deepseek-v3.2')
        api_key = config['api_key']
        
        if not api_key:
            logger.warning(f"LLM API key not configured, using fallback Q&A generation")
            return self._fallback_generate_qa(product_data)
        
        try:
            from openai import OpenAI
            
            client = OpenAI(
                api_key=api_key,
                base_url=config['base_url']
            )
            
            # Build product context
            product_name = product_data.get('name', '该商品')
            product_price = product_data.get('price', '未知')
            description = product_data.get('description', '无描述')
            specs = product_data.get('specs_json', {})
            
            product_context = f"""以下是你需要分析的商品完整信息，请仔细阅读每一段内容后生成问答：

【商品名称】{product_name}
【商品价格】{product_price}
【规格信息】{json.dumps(specs, ensure_ascii=False) if specs else '无'}
【商品完整描述（重要，请逐段分析）】
{description}
"""
            if extracted_info:
                product_context += f"""
商品类目: {extracted_info.get('category', '未知')}
商品关键词: {', '.join(extracted_info.get('keywords', []))}
商品特点: {', '.join(extracted_info.get('key_features', []))}
"""
            
            system_prompt = """你是一个电商客服培训专家。请根据给定的商品信息，生成买家常见问题和客服标准回答。

【核心原则】
所有问答必须围绕"产品本身"和"用法用途"展开，即买家购买后真正会关心的问题：
- 这个东西怎么用？适合什么场景？能解决什么问题？
- 有什么功能？怎么操作？怎么安装？
- 具体参数是多少？和其他产品有什么区别？

【最高优先级原则 - 违反任何一条则视为失败】
1. 所有问答必须100%来源于下方提供的"商品描述"和"规格信息"中的具体内容
2. 严禁生成以下类型的问题，即使商品描述中包含相关信息也不生成：
   × 物流类："运费多少？"、"包邮吗？"、"发什么快递？"
   × 发货类："什么时候发货？"、"当日能发吗？"
   × 售后类："可以退换吗？"、"保修多久？"、"质量有问题怎么办？"
   × 属性类："属于什么类目？"、"是二手的吗？"、"是正品吗？"
   × 通用类："有库存吗？"、"是预售吗？"、"有优惠吗？"、"质量怎么样？"
   × 判断标准：如果把商品名换成另一个完全不同的商品，这个问题仍然成立，那就是通用问题，必须删除
3. 严禁杜撰任何商品描述中不存在的信息
   - 宁可少说，也不能编造。不确定的内容一律不写入回答
4. 禁止回答"请咨询客服"或"联系客服"，因为你就是客服

【只允许生成以下类型的问答——全部围绕产品本身和用法用途】
  * 产品用途和适用场景（这个产品用来做什么？适合什么场景？）
  * 使用方法和操作步骤（怎么用？怎么操作？怎么设置？）
  * 产品功能和特点（有哪些功能？有什么特别的？）
  * 安装方法和接线方式（怎么安装？怎么接？）
  * 产品技术参数（尺寸、功率、电压、温度范围等和使用直接相关的参数）
  * 兼容性和适配信息（能配什么设备？支持什么型号？）
  * 维护保养和常见问题（日常怎么保养？遇到XX情况怎么办？）
  * 包装内容和配件（仅当描述明确列出时）

【问答生成方法】
第一步：仔细阅读商品描述，理解产品是什么、用来做什么
第二步：站在买家角度，想象买家拿到产品后会关心什么——怎么用、用在哪、注意什么
第三步：围绕产品用途和使用方法设计问题，用商品描述中的内容组织回答
第四步：自检——删除所有物流/发货/售后/属性/通用类问题

【问题设计要求】
- 以买家的口吻提问，口语化（"这个怎么用？"、"适合用在哪里？"、"能不能用来...？"）
- 问题必须和产品的实际使用有关，是买家买了产品后真正会问的问题

【回答要求】
- 以专业客服身份回答，开头用"亲"或"您好"
- 商品描述中已有的信息，必须自信、明确、直接地回答
- 技术参数必须与原文完全一致（数值、单位不得更改）
- 操作步骤按原文顺序描述，不遗漏不添加
- 严禁添加商品描述中没有的内容，宁可不提也不能编造
- 语气自然亲切，像真人客服聊天，句末可用"~"、"哦"、"呢"等语气词

请严格按照以下JSON数组格式返回，不要添加任何其他内容：
[
    {
        "question": "买家的问题",
        "answer": "客服的回答"
    }
]

【数量要求】
必须生成至少10个、最多30个问答对，这是硬性要求。
- 即使商品描述较短，也必须从不同角度、不同细节提取信息，确保至少10个问答
- 信息丰富的商品应生成20-30个问答，每个具体信息点都应对应至少一个问答
- 如果描述非常详细，优先覆盖所有关键使用方法和产品功能，不遗漏"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": product_context}
            ]
            
            response = client.chat.completions.create(
                model=config['model'],
                temperature=0.1,  # Very low temperature for strict factual responses
                messages=messages,
                max_tokens=8000,  # Large token limit for comprehensive Q&A
            )
            
            if response and response.choices:
                content = response.choices[0].message.content.strip()
                try:
                    # Handle potential markdown code blocks
                    if content.startswith('```'):
                        content = content.split('```')[1]
                        if content.startswith('json'):
                            content = content[4:]
                    qa_list = json.loads(content)
                    
                    # Validate structure
                    if isinstance(qa_list, list) and len(qa_list) > 0:
                        valid_qa = []
                        for qa in qa_list:
                            if isinstance(qa, dict) and 'question' in qa and 'answer' in qa:
                                valid_qa.append({
                                    'question': str(qa['question']).strip(),
                                    'answer': str(qa['answer']).strip()
                                })
                        if valid_qa:
                            # Enforce max 30 Q&A pairs
                            if len(valid_qa) > 30:
                                valid_qa = valid_qa[:30]
                            logger.info(f"Generated {len(valid_qa)} Q&A pairs for: {product_name[:30]}")
                            # If fewer than 10, retry once with emphasis on minimum
                            if len(valid_qa) < 10:
                                logger.info(f"Only {len(valid_qa)} Q&A generated, retrying for more...")
                                retry_msgs = messages + [
                                    {"role": "assistant", "content": content},
                                    {"role": "user", "content": f"你只生成了{len(valid_qa)}条问答，不满足最低10条的要求。请再补充生成{10 - len(valid_qa)}条以上的问答，同样以JSON数组格式返回，仅返回新增的问答。"}
                                ]
                                try:
                                    retry_resp = client.chat.completions.create(
                                        model=config['model'],
                                        temperature=0.1,
                                        messages=retry_msgs,
                                        max_tokens=4000,
                                    )
                                    if retry_resp and retry_resp.choices:
                                        retry_content = retry_resp.choices[0].message.content.strip()
                                        if retry_content.startswith('```'):
                                            retry_content = retry_content.split('```')[1]
                                            if retry_content.startswith('json'):
                                                retry_content = retry_content[4:]
                                        extra_qa = json.loads(retry_content)
                                        if isinstance(extra_qa, list):
                                            for qa in extra_qa:
                                                if isinstance(qa, dict) and 'question' in qa and 'answer' in qa:
                                                    valid_qa.append({
                                                        'question': str(qa['question']).strip(),
                                                        'answer': str(qa['answer']).strip()
                                                    })
                                            valid_qa = valid_qa[:30]
                                            logger.info(f"After retry: {len(valid_qa)} Q&A pairs for: {product_name[:30]}")
                                except Exception as retry_err:
                                    logger.warning(f"Retry Q&A generation failed: {retry_err}")
                            return valid_qa
                            
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse AI Q&A response as JSON: {e}")
                    
        except Exception as e:
            logger.error(f"LLM API call failed for generate_product_qa: {e}")
        
        return self._fallback_generate_qa(product_data)
    
    def _fallback_generate_qa(self, product_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Generate basic Q&A pairs when AI is unavailable."""
        product_name = product_data.get('name', '该商品')
        price = product_data.get('price', '未知')
        
        return [
            {
                "question": f"{product_name}多少钱？",
                "answer": f"亲，这款商品的价格是{price}，详情可以查看商品页面哦~"
            },
            {
                "question": f"{product_name}有什么颜色/规格？",
                "answer": f"亲，关于这款商品的规格颜色，您可以查看商品详情页，如有特殊需求也可以告诉我哦~"
            },
            {
                "question": f"{product_name}怎么使用？",
                "answer": "亲，商品会附带使用说明，收到后可以参考哦，有问题随时联系我们~"
            },
            {
                "question": f"这款商品适合什么人用？",
                "answer": "亲，这款商品适用范围广，您有特殊需求可以告诉我，我帮您确认是否合适~"
            },
            {
                "question": f"{product_name}售后怎么样？",
                "answer": "亲，我们提供完善的售后服务，有任何问题都可以随时联系我们客服处理~"
            }
        ]


def start_model_health_check_thread():
    """
    Start background thread to periodically check model health.
    This allows automatic recovery to primary model when it becomes available again.
    """
    global _health_check_thread, _health_check_stop_event
    
    if _health_check_thread is not None and _health_check_thread.is_alive():
        logger.info("[模型健康检查] 后台线程已在运行")
        return
    
    _health_check_stop_event.clear()
    
    def health_check_loop():
        logger.info("[模型健康检查] 后台线程启动，每10分钟检查一次模型状态")
        ai_service = AIService()
        
        while not _health_check_stop_event.is_set():
            try:
                # Clear all model health caches to force fresh checks
                ai_service._invalidate_model_health_cache()
                
                # Check health of all configured models
                for model_name in ai_service.MODEL_CONFIGS.keys():
                    is_healthy = ai_service._check_model_health(model_name)
                    status = "可用 ✓" if is_healthy else "不可用 ✗"
                    logger.info(f"[模型健康检查] {model_name}: {status}")
                
            except Exception as e:
                logger.error(f"[模型健康检查] 检查失败: {e}")
            
            # Wait for next check interval (10 minutes)
            _health_check_stop_event.wait(MODEL_HEALTH_CHECK_INTERVAL)
        
        logger.info("[模型健康检查] 后台线程已停止")
    
    _health_check_thread = threading.Thread(target=health_check_loop, daemon=True)
    _health_check_thread.start()


def stop_model_health_check_thread():
    """Stop the background health check thread."""
    global _health_check_stop_event
    _health_check_stop_event.set()
    logger.info("[模型健康检查] 正在停止后台线程...")

