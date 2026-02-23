# -*- coding: utf-8 -*-
"""
Learning service for processing product data and generating Q&A.
"""
import logging
from typing import Dict, List, Any, Optional
from django.db import transaction
from apps.ai.services import AIService
from apps.knowledge.models import KnowledgeBase
from apps.products.models import Product
from apps.ai.models import LearningRecord
from .models import LearningTask

logger = logging.getLogger(__name__)


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
    
    @transaction.atomic
    def process_product(
        self, 
        task: LearningTask,
        product_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single product: save to DB and generate Q&A.
        
        Args:
            task: The learning task
            product_data: Product information from Electron client
        
        Returns:
            Dict with processing result
        """
        try:
            # 1. Create or update product
            product, created = Product.objects.update_or_create(
                shop_id=task.shop_id,
                platform_product_id=product_data.get('platform_product_id', ''),
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
            
            # 4. Save Q&A to knowledge base
            qa_count = 0
            for qa in qa_pairs:
                question = qa.get('question', '')
                answer = qa.get('answer', '')
                
                if not question or not answer:
                    continue
                
                # Check for duplicates - only within the SAME product to allow each product to have its own Q&A
                exists = KnowledgeBase.objects.filter(
                    shop_id=task.shop_id,
                    product=product,  # Only check duplicates within the same product
                    question__icontains=question[:50]
                ).exists()
                
                if not exists:
                    KnowledgeBase.objects.create(
                        question=question,
                        answer=answer,
                        shop_id=task.shop_id,
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
            
            # Save product knowledge as a learning record
            if product.description:
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
            
            # 5. Update task progress
            task.processed_count += 1
            task.success_count += 1
            task.qa_generated += qa_count
            task.save(update_fields=['processed_count', 'success_count', 'qa_generated'])
            
            task.add_log(f'完成商品学习，生成 {qa_count} 条问答')
            
            return {
                'success': True,
                'product_id': product.product_id,
                'qa_count': qa_count,
                'message': f'成功处理商品，生成 {qa_count} 条问答'
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
    
    def complete_task(self, task: LearningTask) -> None:
        """Mark task as completed."""
        task.mark_completed()
        task.add_log(
            f'学习完成！成功: {task.success_count}, '
            f'失败: {task.fail_count}, '
            f'生成问答: {task.qa_generated}'
        )
