# -*- coding: utf-8 -*-
"""
Learning service for processing product data and generating Q&A.
"""
import logging
import difflib
from typing import Dict, List, Any, Optional, Tuple
from django.db import transaction
from apps.ai.services import AIService
from apps.knowledge.models import KnowledgeBase
from apps.products.models import Product
from apps.ai.models import LearningRecord
from .models import LearningTask

logger = logging.getLogger(__name__)

# Similarity threshold for detecting Q&A conflicts
CONFLICT_SIMILARITY_THRESHOLD = 0.6


class LearningService:
    """
    Service for auto-learning product knowledge.
    """
    
    def __init__(self):
        self.ai_service = AIService()
    
    def create_task(self, shop_id: str, platform: str, owner_id: int) -> LearningTask:
        """Create a new learning task."""
        task = LearningTask.objects.create(
            shop_id=shop_id,
            platform=platform,
            owner_id=owner_id,
            status='pending'
        )
        task.add_log(f'学习任务已创建，平台: {platform}')
        return task
    
    def start_task(self, task: LearningTask, total_products: int) -> None:
        """Mark task as started with total product count."""
        task.status = 'running'
        task.total_products = total_products
        task.save(update_fields=['status', 'total_products'])
        task.add_log(f'开始学习，共 {total_products} 个商品')
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity ratio between two texts."""
        return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    
    def _find_existing_knowledge(
        self,
        shop_id: str,
        product: Product
    ) -> List[Dict[str, Any]]:
        """Find existing knowledge base entries for a product."""
        existing = KnowledgeBase.objects.filter(
            shop_id=shop_id,
            product=product
        ).values('id', 'question', 'answer', 'is_correct', 'source')
        return list(existing)
    
    def _detect_conflicts(
        self,
        new_qa_pairs: List[Dict[str, str]],
        existing_qa: List[Dict[str, Any]]
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Detect conflicts between new Q&A pairs and existing knowledge.
        
        Returns:
            Tuple of (conflicts, new_only, skip)
            - conflicts: New Q&A that conflicts with existing (same question, different answer)
            - new_only: New Q&A that doesn't exist yet
            - skip: New Q&A that already exists identically
        """
        conflicts = []
        new_only = []
        skip = []
        
        for new_qa in new_qa_pairs:
            new_q = new_qa.get('question', '').strip()
            new_a = new_qa.get('answer', '').strip()
            
            if not new_q or not new_a:
                continue
            
            found_match = False
            for existing in existing_qa:
                existing_q = existing.get('question', '').strip()
                existing_a = existing.get('answer', '').strip()
                
                # Check if questions are similar
                q_similarity = self._calculate_similarity(new_q, existing_q)
                
                if q_similarity >= CONFLICT_SIMILARITY_THRESHOLD:
                    found_match = True
                    
                    # Check if answers are also similar (not a conflict) or different (conflict)
                    a_similarity = self._calculate_similarity(new_a, existing_a)
                    
                    if a_similarity >= 0.85:
                        # Same question, same answer - skip
                        skip.append({
                            'question': new_q,
                            'answer': new_a,
                            'existing_id': existing.get('id'),
                            'reason': 'duplicate'
                        })
                    else:
                        # Same question, different answer - conflict!
                        conflicts.append({
                            'question': new_q,
                            'new_answer': new_a,
                            'existing_id': existing.get('id'),
                            'existing_question': existing_q,
                            'existing_answer': existing_a,
                            'existing_is_correct': existing.get('is_correct', False),
                            'existing_source': existing.get('source', ''),
                            'question_similarity': round(q_similarity, 2),
                            'answer_similarity': round(a_similarity, 2)
                        })
                    break
            
            if not found_match:
                new_only.append({
                    'question': new_q,
                    'answer': new_a
                })
        
        return conflicts, new_only, skip
    
    def check_product_learned(
        self,
        shop_id: str,
        platform_product_id: str
    ) -> Dict[str, Any]:
        """
        Check if a product has already been learned.
        
        Returns:
            Dict with: has_learned, product_id, existing_qa_count, existing_qa
        """
        try:
            product = Product.objects.get(
                shop_id=shop_id,
                platform_product_id=platform_product_id
            )
            existing_qa = self._find_existing_knowledge(shop_id, product)
            
            return {
                'has_learned': True,
                'product_id': product.product_id,
                'product_name': product.name,
                'existing_qa_count': len(existing_qa),
                'existing_qa': existing_qa
            }
        except Product.DoesNotExist:
            return {
                'has_learned': False,
                'product_id': None,
                'product_name': None,
                'existing_qa_count': 0,
                'existing_qa': []
            }
    
    @transaction.atomic
    def process_product(
        self, 
        task: LearningTask,
        product_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single product: save to DB and generate Q&A.
        Now with conflict detection for already-learned products.
        
        Args:
            task: The learning task
            product_data: Product information from Electron client
        
        Returns:
            Dict with processing result including conflicts
        """
        try:
            platform_product_id = product_data.get('platform_product_id', '')
            
            # Check if product already exists (already learned)
            existing_check = self.check_product_learned(task.shop_id, platform_product_id)
            was_learned = existing_check['has_learned']
            existing_qa = existing_check.get('existing_qa', [])
            
            # 1. Create or update product
            product, created = Product.objects.update_or_create(
                shop_id=task.shop_id,
                platform_product_id=platform_product_id,
                defaults={
                    'name': product_data.get('name', ''),
                    'price': product_data.get('price', 0),
                    'stock': product_data.get('stock', 0),
                    'sku': product_data.get('sku', ''),
                    'description': product_data.get('description', ''),
                    'image_url': product_data.get('image_url', ''),
                    'specs_json': product_data.get('specs', {}),
                    'learning_status': 'learned',
                    'status': 'active',
                }
            )
            
            action = '新增' if created else '更新'
            if was_learned:
                task.add_log(f'[重复学习] {action}商品: {product.name[:30]}... (已有 {len(existing_qa)} 条知识)')
            else:
                task.add_log(f'{action}商品: {product.name[:30]}...')
            
            # 2. Build product data dict for AI processing
            ai_product_data = {
                'name': product.name,
                'price': str(product.price),
                'description': product.description,
                'specs_json': product_data.get('specs', {})
            }
            
            # 3. Extract product info using AI
            product_info = self.ai_service.extract_product_info(ai_product_data)
            
            # 4. Generate Q&A pairs using AI
            qa_pairs = self.ai_service.generate_product_qa(ai_product_data, product_info)
            
            # 5. Detect conflicts with existing knowledge
            conflicts, new_only, skipped = self._detect_conflicts(qa_pairs, existing_qa)
            
            if was_learned:
                task.add_log(
                    f'知识检测: 新增 {len(new_only)} 条, '
                    f'冲突 {len(conflicts)} 条, '
                    f'跳过 {len(skipped)} 条'
                )
            
            # 6. Save new Q&A to knowledge base (only non-conflicting new ones)
            qa_count = 0
            for qa in new_only:
                question = qa.get('question', '')
                answer = qa.get('answer', '')
                
                if not question or not answer:
                    continue
                
                from apps.knowledge.utils import infer_shop_id
                resolved_shop_id = infer_shop_id(owner_id=task.owner_id, shop_id=task.shop_id)
                KnowledgeBase.objects.create(
                    question=question,
                    answer=answer,
                    shop_id=resolved_shop_id,
                    owner_id=task.owner_id,
                    category=product_info.get('category', '商品咨询'),
                    keywords=','.join(product_info.get('keywords', [])[:5]),
                    source='auto_learned',
                    product=product,
                    is_correct=False,  # Needs manual review
                )
                qa_count += 1
                
                # Also save as learning record for future local model training
                try:
                    LearningRecord.objects.create(
                        record_type='qa_pair',
                        instruction=question,
                        response=answer,
                        product_name=product.name[:255],
                        raw_knowledge=product.description[:2000] if product.description else '',
                        shop_id=task.shop_id,
                        owner_id=task.owner_id,
                    )
                except Exception as lr_err:
                    logger.warning(f"Failed to save learning record: {lr_err}")
            
            # Save product knowledge as a learning record (only for new products)
            if created and product.description:
                try:
                    LearningRecord.objects.create(
                        record_type='product_knowledge',
                        instruction=f"请介绍一下{product.name[:50]}",
                        response=product.description[:2000],
                        product_name=product.name[:255],
                        raw_knowledge=product.description[:2000],
                        shop_id=task.shop_id,
                        owner_id=task.owner_id,
                    )
                except Exception as pk_err:
                    logger.warning(f"Failed to save product knowledge record: {pk_err}")
            
            # 7. Update task progress
            task.processed_count += 1
            task.success_count += 1
            task.qa_generated += qa_count
            task.save(update_fields=['processed_count', 'success_count', 'qa_generated'])
            
            if conflicts:
                task.add_log(f'完成商品学习，新增 {qa_count} 条问答，发现 {len(conflicts)} 条冲突需要确认')
            else:
                task.add_log(f'完成商品学习，生成 {qa_count} 条问答')
            
            return {
                'success': True,
                'product_id': product.product_id,
                'qa_count': qa_count,
                'was_learned': was_learned,
                'conflicts': conflicts,
                'conflicts_count': len(conflicts),
                'skipped_count': len(skipped),
                'message': f'成功处理商品，新增 {qa_count} 条问答' + (
                    f'，发现 {len(conflicts)} 条冲突' if conflicts else ''
                )
            }
            
        except Exception as e:
            task.processed_count += 1
            task.fail_count += 1
            task.save(update_fields=['processed_count', 'fail_count'])
            task.add_log(f'处理失败: {str(e)}', level='error')
            
            return {
                'success': False,
                'message': str(e)
            }
    
    def resolve_conflict(
        self,
        conflict_id: int,
        action: str,
        new_answer: str = None
    ) -> Dict[str, Any]:
        """
        Resolve a knowledge conflict.
        
        Args:
            conflict_id: ID of the existing knowledge entry
            action: 'keep_old', 'use_new', or 'merge'
            new_answer: New answer text (required for 'use_new' and 'merge')
        
        Returns:
            Dict with resolution result
        """
        try:
            kb_entry = KnowledgeBase.objects.get(id=conflict_id)
            
            if action == 'keep_old':
                # Keep existing, do nothing
                return {
                    'success': True,
                    'action': 'kept_old',
                    'message': '保留原有知识'
                }
            elif action == 'use_new':
                # Replace with new answer
                if not new_answer:
                    return {'success': False, 'message': '缺少新答案内容'}
                kb_entry.answer = new_answer
                kb_entry.is_correct = False  # Reset verification status
                kb_entry.source = 'auto_learned'
                kb_entry.save(update_fields=['answer', 'is_correct', 'source', 'updated_at'])
                return {
                    'success': True,
                    'action': 'replaced',
                    'message': '已替换为新知识'
                }
            elif action == 'merge':
                # Merge both answers
                if not new_answer:
                    return {'success': False, 'message': '缺少新答案内容'}
                merged = f"{kb_entry.answer}\n\n【补充】{new_answer}"
                kb_entry.answer = merged
                kb_entry.is_correct = False
                kb_entry.save(update_fields=['answer', 'is_correct', 'updated_at'])
                return {
                    'success': True,
                    'action': 'merged',
                    'message': '已合并新旧知识'
                }
            else:
                return {'success': False, 'message': f'未知操作: {action}'}
                
        except KnowledgeBase.DoesNotExist:
            return {'success': False, 'message': '知识条目不存在'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def complete_task(self, task: LearningTask) -> None:
        """Mark task as completed."""
        task.mark_completed()
        task.add_log(
            f'学习完成！成功: {task.success_count}, '
            f'失败: {task.fail_count}, '
            f'生成问答: {task.qa_generated}'
        )
