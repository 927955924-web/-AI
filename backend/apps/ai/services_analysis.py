# -*- coding: utf-8 -*-
"""
Daily Conversation Analysis Service.

Analyzes previous day's ConversationRecords using DeepSeek/Doubao,
extracts optimized Q&A pairs, saves to KnowledgeBase per product,
then deletes processed records to prevent data bloat.
"""
import json
import re
import time
import logging
import difflib
from datetime import date, timedelta
from collections import defaultdict
from typing import Optional, Dict, List, Any, Tuple

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Similarity thresholds (consistent with LearningService)
CONFLICT_SIMILARITY_THRESHOLD = 0.6
ANSWER_DUPLICATE_THRESHOLD = 0.85

# Batch limits
MAX_CONVERSATIONS_PER_LLM_CALL = 50
DELETE_BATCH_SIZE = 500


class ConversationAnalysisService:
    """
    Service that runs daily analysis of conversation records,
    extracting and saving optimized Q&A pairs into the knowledge base.
    """

    def __init__(self):
        self._ai_service = None

    @property
    def ai_service(self):
        if self._ai_service is None:
            from .services import AIService
            self._ai_service = AIService()
        return self._ai_service

    def run_daily_analysis(self, target_date: date = None) -> Dict[str, Any]:
        """
        Main entry point: analyze conversations for a given date.
        Defaults to yesterday.

        Returns summary dict with stats.
        """
        if target_date is None:
            target_date = (timezone.localdate() - timedelta(days=1))

        start_time = time.time()
        logger.info(f"[每日分析] 开始分析 {target_date} 的对话记录...")

        summary = {
            'date': str(target_date),
            'total_records': 0,
            'shops_processed': 0,
            'product_groups': 0,
            'general_groups': 0,
            'qa_saved': 0,
            'qa_skipped': 0,
            'qa_conflicts': 0,
            'records_deleted': 0,
            'errors': [],
        }

        try:
            records = self._collect_records(target_date)
            summary['total_records'] = records.count()

            if summary['total_records'] == 0:
                logger.info(f"[每日分析] {target_date} 没有待分析的对话记录")
                return summary

            logger.info(f"[每日分析] 收集到 {summary['total_records']} 条对话记录")

            # Group by shop
            shop_groups = defaultdict(list)
            for record in records.select_related('shop', 'owner'):
                shop_id = record.shop_id or '__no_shop__'
                shop_groups[shop_id].append(record)

            # Filter out shops that have auto_learn_summary disabled
            from apps.shops.models import Shop
            disabled_shops = set(
                Shop.objects.filter(
                    auto_learn_summary=False
                ).values_list('shop_id', flat=True)
            )

            for shop_id, shop_records in shop_groups.items():
                if shop_id != '__no_shop__' and shop_id in disabled_shops:
                    logger.info(
                        f"[每日分析] 店铺 {shop_id} 已关闭自动学习，跳过 "
                        f"{len(shop_records)} 条记录"
                    )
                    continue

                summary['shops_processed'] += 1
                try:
                    self._process_shop_records(
                        shop_id if shop_id != '__no_shop__' else None,
                        shop_records,
                        summary
                    )
                except Exception as e:
                    error_msg = f"店铺 {shop_id} 分析失败: {e}"
                    logger.error(f"[每日分析] {error_msg}")
                    summary['errors'].append(error_msg)

            # Delete processed records
            deleted = self._delete_processed_records(records)
            summary['records_deleted'] = deleted

        except Exception as e:
            error_msg = f"分析过程出错: {e}"
            logger.error(f"[每日分析] {error_msg}", exc_info=True)
            summary['errors'].append(error_msg)

        elapsed = time.time() - start_time
        summary['execution_time'] = round(elapsed, 2)

        logger.info(
            f"[每日分析] 完成! 耗时 {elapsed:.1f}s | "
            f"记录: {summary['total_records']} | "
            f"保存QA: {summary['qa_saved']} | "
            f"跳过: {summary['qa_skipped']} | "
            f"冲突: {summary['qa_conflicts']} | "
            f"删除: {summary['records_deleted']} | "
            f"错误: {len(summary['errors'])}"
        )
        return summary

    def _collect_records(self, target_date: date):
        """Collect conversation records for the target date."""
        from .models import ConversationRecord
        return ConversationRecord.objects.filter(
            created_at__date=target_date,
        ).exclude(
            quality='rejected'
        )

    def _process_shop_records(
        self,
        shop_id: Optional[str],
        records: List,
        summary: Dict[str, Any]
    ):
        """Process all records for a single shop."""
        # Get owner from first record
        owner_id = None
        for r in records:
            if r.owner_id:
                owner_id = r.owner_id
                break

        # Group by product
        product_groups = self._group_by_product(records, shop_id)

        for product_id, group_records in product_groups.items():
            try:
                if product_id is not None:
                    summary['product_groups'] += 1
                    qa_pairs = self._analyze_product_conversations(
                        group_records, product_id, shop_id
                    )
                else:
                    summary['general_groups'] += 1
                    qa_pairs = self._analyze_general_conversations(
                        group_records, shop_id
                    )

                if qa_pairs:
                    counts = self._save_qa_pairs(
                        qa_pairs, shop_id, owner_id, product_id
                    )
                    summary['qa_saved'] += counts.get('saved', 0)
                    summary['qa_skipped'] += counts.get('skipped', 0)
                    summary['qa_conflicts'] += counts.get('conflicts', 0)

            except Exception as e:
                product_label = product_id or '通用'
                error_msg = f"商品 {product_label} 分析失败: {e}"
                logger.error(f"[每日分析] {error_msg}")
                summary['errors'].append(error_msg)

    def _match_product_id(self, record, shop_id: str) -> Optional[str]:
        """
        Smart-match a conversation record to a product_id.
        Priority: order_info > context keywords > name fuzzy match.
        """
        if not shop_id:
            return None

        from apps.products.models import Product

        # Priority 1: Parse order_info JSON
        if record.order_info:
            try:
                order_data = json.loads(record.order_info) if isinstance(
                    record.order_info, str
                ) else record.order_info
                product_names = []
                # New format: {orders: [{products: [{name: ...}]}]}
                for order in order_data.get('orders', []):
                    for product in order.get('products', []):
                        name = product.get('name', '').strip()
                        if name:
                            product_names.append(name)
                # Old format: {products: [{name: ...}]}
                if not product_names:
                    for product in order_data.get('products', []):
                        name = product.get('name', '').strip()
                        if name:
                            product_names.append(name)

                for name in product_names:
                    matched = Product.objects.filter(
                        shop_id=shop_id,
                        status='active',
                        name__icontains=name[:20]
                    ).values_list('product_id', flat=True).first()
                    if matched:
                        return matched
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        # Priority 2: Extract product keywords from conversation_context
        search_text = f"{record.buyer_message} {record.conversation_context or ''}"

        # Look for 【商品名】 patterns
        bracketed = re.findall(r'【(.*?)】', search_text)
        for kw in bracketed:
            if len(kw) >= 2:
                matched = Product.objects.filter(
                    shop_id=shop_id,
                    status='active',
                    name__icontains=kw[:20]
                ).values_list('product_id', flat=True).first()
                if matched:
                    return matched

        # Priority 3: Token-based fuzzy match against shop products
        shop_products = list(Product.objects.filter(
            shop_id=shop_id, status='active'
        ).values('product_id', 'name', 'platform_product_id')[:200])

        if not shop_products:
            return None

        text_lower = search_text.lower()
        best_score = 0
        best_pid = None

        for p in shop_products:
            pname = (p['name'] or '').lower()
            ppid = p['platform_product_id'] or ''

            # Exact platform ID match in text
            if ppid and ppid in search_text:
                return p['product_id']

            # Token match
            tokens = [t for t in re.split(
                r'[\s/\-\+\(\)（）【】\[\]]+', pname
            ) if len(t) >= 2]
            if tokens:
                matched_tokens = sum(1 for t in tokens if t in text_lower)
                score = matched_tokens / len(tokens)
                if score > best_score:
                    best_score = score
                    best_pid = p['product_id']

        if best_score >= 0.3 and best_pid:
            return best_pid

        return None

    def _group_by_product(
        self, records: List, shop_id: Optional[str]
    ) -> Dict[Optional[str], List]:
        """Group conversation records by product_id."""
        groups = defaultdict(list)
        for record in records:
            product_id = self._match_product_id(record, shop_id) if shop_id else None
            groups[product_id].append(record)

        product_count = sum(1 for k in groups if k is not None)
        general_count = len(groups.get(None, []))
        logger.info(
            f"[每日分析] 店铺 {shop_id}: "
            f"{product_count} 个商品组, {general_count} 条通用对话"
        )
        return dict(groups)

    def _format_conversations(self, records: List) -> str:
        """Format conversation records into text for LLM prompt."""
        lines = []
        for i, record in enumerate(records):
            lines.append(
                f"[{i+1}] 买家: {record.buyer_message}\n"
                f"    客服: {record.customer_reply}"
            )
        return '\n---\n'.join(lines)

    def _analyze_product_conversations(
        self,
        conversations: List,
        product_id: str,
        shop_id: Optional[str]
    ) -> List[Dict[str, str]]:
        """Analyze conversations for a specific product, extract Q&A pairs."""
        from apps.products.models import Product

        product = None
        product_name = '未知商品'
        try:
            product = Product.objects.get(product_id=product_id)
            product_name = product.name
        except Product.DoesNotExist:
            pass

        # Process in batches
        all_qa = []
        for batch_start in range(0, len(conversations), MAX_CONVERSATIONS_PER_LLM_CALL):
            batch = conversations[batch_start:batch_start + MAX_CONVERSATIONS_PER_LLM_CALL]
            conv_text = self._format_conversations(batch)

            prompt = (
                f"你是电商客服知识库优化专家。请分析以下买家-客服真实对话记录，"
                f"提取和优化出标准问答对。\n\n"
                f"商品：{product_name}\n\n"
                f"对话记录（共{len(batch)}条）：\n{conv_text}\n\n"
                f"提取规则：\n"
                f"1. 只提取与该商品功能、用法、参数、规格相关的问答，"
                f"忽略物流/售后/通用问题\n"
                f"2. 合并相似问题，提炼为规范化问题\n"
                f"3. 答案基于对话原文优化，保持专业亲切，60字以内\n"
                f"4. 严禁编造对话中没有的信息\n"
                f"5. 过滤低质量对话（纯表情、无意义闲聊、重复问候）\n\n"
                f"返回JSON数组，无其他内容：\n"
                f'[{{"question": "...", "answer": "..."}}]\n\n'
                f"数量要求：3-20条，如果有效对话不足3条可以返回空数组 []"
            )

            qa_pairs = self._call_llm_for_qa(prompt)
            if qa_pairs:
                all_qa.extend(qa_pairs)

        if all_qa:
            logger.info(
                f"[每日分析] 商品 '{product_name}' 提取了 {len(all_qa)} 条Q&A"
            )
        return all_qa

    def _analyze_general_conversations(
        self,
        conversations: List,
        shop_id: Optional[str]
    ) -> List[Dict[str, str]]:
        """Analyze non-product conversations, extract general Q&A."""
        all_qa = []
        for batch_start in range(0, len(conversations), MAX_CONVERSATIONS_PER_LLM_CALL):
            batch = conversations[batch_start:batch_start + MAX_CONVERSATIONS_PER_LLM_CALL]
            conv_text = self._format_conversations(batch)

            prompt = (
                f"你是电商客服知识库优化专家。请分析以下通用客服对话记录，"
                f"提取可复用的标准问答。\n\n"
                f"店铺对话记录（共{len(batch)}条）：\n{conv_text}\n\n"
                f"提取规则：\n"
                f"1. 只提取通用性强、可复用的客服话术\n"
                f"2. 排除与特定商品相关的问题\n"
                f"3. 排除个性化问题（如特定订单号查询）\n"
                f"4. 问题规范化，答案标准化，60字以内\n"
                f"5. 过滤低质量对话（纯表情、无意义闲聊）\n\n"
                f"返回JSON数组，无其他内容：\n"
                f'[{{"question": "...", "answer": "..."}}]\n\n'
                f"数量要求：1-10条，如果没有有价值的通用问答可以返回空数组 []"
            )

            qa_pairs = self._call_llm_for_qa(prompt)
            if qa_pairs:
                all_qa.extend(qa_pairs)

        if all_qa:
            logger.info(
                f"[每日分析] 通用对话提取了 {len(all_qa)} 条Q&A"
            )
        return all_qa

    def _call_llm_for_qa(self, prompt: str) -> List[Dict[str, str]]:
        """
        Call LLM to extract Q&A pairs from conversations.
        Uses DeepSeek as primary, Doubao as fallback.
        Returns list of {question, answer} dicts.
        """
        from .services import AIService

        service = self.ai_service

        # Try DeepSeek first (cost-effective for analysis)
        models_to_try = ['deepseek-v3.2', 'doubao-seed-2.0-pro']

        for model in models_to_try:
            try:
                config = service._get_llm_config(model=model)
                api_key = config.get('api_key', '')
                if not api_key:
                    continue

                from openai import OpenAI
                client = OpenAI(
                    api_key=api_key,
                    base_url=config['base_url'],
                    timeout=120
                )

                response = client.chat.completions.create(
                    model=config['model'],
                    temperature=0.1,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是电商客服知识库优化专家。严格按要求返回JSON格式。"
                        },
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=4000,
                )

                if response and response.choices:
                    content = response.choices[0].message.content.strip()

                    # Save token usage
                    if hasattr(response, 'usage') and response.usage:
                        service._save_token_usage(
                            prompt_tokens=response.usage.prompt_tokens or 0,
                            completion_tokens=response.usage.completion_tokens or 0,
                            total_tokens=response.usage.total_tokens or 0,
                            model_version=config['model'],
                            request_type='qa_generation'
                        )

                    return self._parse_qa_response(content)

            except Exception as e:
                logger.warning(
                    f"[每日分析] 模型 {model} 调用失败: {str(e)[:100]}，尝试下一个"
                )
                continue

        logger.error("[每日分析] 所有模型调用失败，无法提取Q&A")
        return []

    def _parse_qa_response(self, content: str) -> List[Dict[str, str]]:
        """Parse LLM response into Q&A pairs."""
        # Handle markdown code blocks
        if '```' in content:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1)

        try:
            qa_list = json.loads(content)
            if not isinstance(qa_list, list):
                return []

            valid_qa = []
            for qa in qa_list:
                if isinstance(qa, dict) and qa.get('question') and qa.get('answer'):
                    q = str(qa['question']).strip()
                    a = str(qa['answer']).strip()
                    if len(q) >= 2 and len(a) >= 2:
                        valid_qa.append({'question': q, 'answer': a})

            return valid_qa

        except json.JSONDecodeError as e:
            logger.warning(f"[每日分析] JSON解析失败: {e}, 内容: {content[:200]}")
            return []

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity ratio between two texts."""
        return difflib.SequenceMatcher(
            None, text1.lower(), text2.lower()
        ).ratio()

    def _save_qa_pairs(
        self,
        qa_pairs: List[Dict[str, str]],
        shop_id: Optional[str],
        owner_id: Optional[int],
        product_id: Optional[str]
    ) -> Dict[str, int]:
        """
        Save Q&A pairs to KnowledgeBase with conflict detection.
        Returns counts: {saved, skipped, conflicts}.
        """
        from apps.knowledge.models import KnowledgeBase

        counts = {'saved': 0, 'skipped': 0, 'conflicts': 0}

        # Fetch existing KB entries for this shop+product
        existing_qs = KnowledgeBase.objects.filter(shop_id=shop_id)
        if product_id:
            existing_qs = existing_qs.filter(product_id=product_id)
        else:
            existing_qs = existing_qs.filter(product__isnull=True)

        existing_entries = list(
            existing_qs.values('id', 'question', 'answer', 'is_correct', 'source')
        )

        for qa in qa_pairs:
            new_q = qa['question'].strip()
            new_a = qa['answer'].strip()

            if not new_q or not new_a:
                continue

            # Check against existing entries
            found_match = False
            for existing in existing_entries:
                existing_q = existing.get('question', '').strip()
                existing_a = existing.get('answer', '').strip()

                q_similarity = self._calculate_similarity(new_q, existing_q)

                if q_similarity >= CONFLICT_SIMILARITY_THRESHOLD:
                    found_match = True
                    a_similarity = self._calculate_similarity(new_a, existing_a)

                    if a_similarity >= ANSWER_DUPLICATE_THRESHOLD:
                        # Duplicate - skip
                        counts['skipped'] += 1
                        logger.debug(
                            f"[每日分析] 跳过重复: '{new_q[:30]}...' "
                            f"(问题相似度: {q_similarity:.2f}, "
                            f"答案相似度: {a_similarity:.2f})"
                        )
                    else:
                        # Conflict: same question, different answer
                        counts['conflicts'] += 1
                        if existing.get('is_correct'):
                            # Keep human-verified answer
                            logger.info(
                                f"[每日分析] 冲突保留已确认答案: '{new_q[:30]}...'"
                            )
                        else:
                            # Update with new (potentially better) answer
                            KnowledgeBase.objects.filter(
                                id=existing['id']
                            ).update(
                                answer=new_a,
                                source='daily_analysis'
                            )
                            logger.info(
                                f"[每日分析] 冲突更新答案: '{new_q[:30]}...' "
                                f"(旧相似度: {a_similarity:.2f})"
                            )
                    break

            if not found_match:
                # New entry - save
                from apps.knowledge.utils import infer_shop_id
                resolved_shop_id = infer_shop_id(owner_id=owner_id, shop_id=shop_id)
                KnowledgeBase.objects.create(
                    question=new_q,
                    answer=new_a,
                    is_correct=False,
                    source='daily_analysis',
                    shop_id=resolved_shop_id,
                    owner_id=owner_id,
                    product_id=product_id,
                )
                counts['saved'] += 1

                # Add to existing list for subsequent dedup within this batch
                existing_entries.append({
                    'id': None,
                    'question': new_q,
                    'answer': new_a,
                    'is_correct': False,
                    'source': 'daily_analysis',
                })

        logger.info(
            f"[每日分析] 保存结果 - "
            f"新增: {counts['saved']}, "
            f"跳过: {counts['skipped']}, "
            f"冲突: {counts['conflicts']}"
        )
        return counts

    def _delete_processed_records(self, records) -> int:
        """Delete processed conversation records in batches."""
        total_deleted = 0
        record_ids = list(records.values_list('id', flat=True))

        for batch_start in range(0, len(record_ids), DELETE_BATCH_SIZE):
            batch_ids = record_ids[batch_start:batch_start + DELETE_BATCH_SIZE]
            from .models import ConversationRecord
            deleted_count, _ = ConversationRecord.objects.filter(
                id__in=batch_ids
            ).delete()
            total_deleted += deleted_count

        logger.info(f"[每日分析] 删除了 {total_deleted} 条对话记录")
        return total_deleted
