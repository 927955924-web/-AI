# -*- coding: utf-8 -*-
"""
AI Vision Learning Agent Service.

This module provides an AI-driven learning agent that uses vision language models
to analyze page screenshots and make intelligent decisions about page navigation
and product information extraction.
"""
import json
import logging
from typing import Dict, Any, List, Optional
from .services import AIService

logger = logging.getLogger(__name__)


class VisionLearningAgent:
    """
    AI Vision Learning Agent for automated product learning.
    
    This agent uses vision language models to:
    1. Analyze page screenshots
    2. Identify checked products in list pages
    3. Navigate to product detail pages
    4. Extract product information
    5. Generate knowledge base entries
    """
    
    # Default vision model
    DEFAULT_VISION_MODEL = 'qwen-vl-plus'
    
    # Maximum scroll attempts per page
    MAX_SCROLL_ATTEMPTS = 5
    
    # Maximum products to process in one session
    MAX_PRODUCTS_PER_SESSION = 50
    
    def __init__(self, model: str = None):
        """
        Initialize the vision learning agent.
        
        Args:
            model: Vision model to use (default: qwen-vl-plus)
        """
        self.ai_service = AIService()
        self.model = model or self.DEFAULT_VISION_MODEL
        self.session_state = {
            'products_processed': 0,
            'products_extracted': [],
            'current_phase': 'idle',  # idle, list, detail
            'scroll_count': 0,
            'errors': [],
        }
    
    def reset_session(self):
        """Reset the agent session state."""
        self.session_state = {
            'products_processed': 0,
            'products_extracted': [],
            'current_phase': 'idle',
            'scroll_count': 0,
            'errors': [],
        }
    
    def analyze_page(
        self,
        image_base64: str,
        page_type: str = 'list'
    ) -> Dict[str, Any]:
        """
        Analyze a page screenshot and determine the next action.
        
        Args:
            image_base64: Base64 encoded page screenshot
            page_type: 'list' for product list page, 'detail' for detail page
        
        Returns:
            dict with: success, action, data, error
            action types: 'click', 'scroll', 'extract', 'back', 'done'
        """
        self.session_state['current_phase'] = page_type
        
        result = self.ai_service.analyze_page_screenshot(
            image_base64=image_base64,
            page_type=page_type,
            model=self.model
        )
        
        if not result['success']:
            self.session_state['errors'].append({
                'phase': page_type,
                'error': result['error']
            })
        
        return result
    
    def process_extraction_result(
        self,
        extraction_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process the extracted product information and generate Q&A pairs.
        
        Args:
            extraction_data: Product information extracted from detail page
        
        Returns:
            dict with: success, product_data, qa_pairs, error
        """
        if not extraction_data or 'product_info' not in extraction_data:
            return {
                'success': False,
                'product_data': None,
                'qa_pairs': [],
                'error': 'No product info in extraction data'
            }
        
        product_info = extraction_data['product_info']
        
        # Build product data structure for Q&A generation
        product_data = {
            'name': product_info.get('name', ''),
            'price': product_info.get('price', ''),
            'description': product_info.get('description', ''),
            'specs_json': {
                'specs': product_info.get('specs', []),
                'features': product_info.get('features', [])
            }
        }
        
        # Generate Q&A pairs using AI
        try:
            qa_pairs = self.ai_service.generate_product_qa(product_data)
        except Exception as e:
            logger.error(f"Q&A generation failed: {e}")
            qa_pairs = []
        
        # Update session state
        self.session_state['products_processed'] += 1
        self.session_state['products_extracted'].append({
            'name': product_data['name'],
            'qa_count': len(qa_pairs)
        })
        
        return {
            'success': True,
            'product_data': product_data,
            'qa_pairs': qa_pairs,
            'error': None
        }
    
    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current learning session.
        
        Returns:
            dict with session statistics
        """
        return {
            'products_processed': self.session_state['products_processed'],
            'products_extracted': self.session_state['products_extracted'],
            'current_phase': self.session_state['current_phase'],
            'scroll_count': self.session_state['scroll_count'],
            'error_count': len(self.session_state['errors']),
            'errors': self.session_state['errors'][-5:] if self.session_state['errors'] else []
        }
    
    def should_continue(self) -> bool:
        """
        Check if the agent should continue processing.
        
        Returns:
            bool: True if should continue, False otherwise
        """
        # Stop if max products reached
        if self.session_state['products_processed'] >= self.MAX_PRODUCTS_PER_SESSION:
            logger.info(f"Max products reached: {self.MAX_PRODUCTS_PER_SESSION}")
            return False
        
        # Stop if too many consecutive errors
        recent_errors = self.session_state['errors'][-3:]
        if len(recent_errors) >= 3:
            logger.warning("Too many consecutive errors, stopping")
            return False
        
        return True
    
    def increment_scroll_count(self):
        """Increment scroll count for current page."""
        self.session_state['scroll_count'] += 1
    
    def reset_scroll_count(self):
        """Reset scroll count (when navigating to new page)."""
        self.session_state['scroll_count'] = 0
    
    def can_scroll_more(self) -> bool:
        """Check if more scrolling is allowed."""
        return self.session_state['scroll_count'] < self.MAX_SCROLL_ATTEMPTS


class VisionAgentManager:
    """
    Manager for vision learning agent instances.
    Handles agent lifecycle and coordinates with knowledge base.
    """
    
    _instances: Dict[str, VisionLearningAgent] = {}
    
    @classmethod
    def get_agent(cls, session_id: str, model: str = None) -> VisionLearningAgent:
        """
        Get or create a vision agent for a session.
        
        Args:
            session_id: Unique session identifier
            model: Vision model to use
        
        Returns:
            VisionLearningAgent instance
        """
        if session_id not in cls._instances:
            cls._instances[session_id] = VisionLearningAgent(model=model)
        return cls._instances[session_id]
    
    @classmethod
    def remove_agent(cls, session_id: str):
        """Remove an agent instance."""
        if session_id in cls._instances:
            del cls._instances[session_id]
    
    @classmethod
    def get_all_sessions(cls) -> List[str]:
        """Get all active session IDs."""
        return list(cls._instances.keys())
    
    @classmethod
    def save_to_knowledge_base(
        cls,
        product_data: Dict[str, Any],
        qa_pairs: List[Dict[str, str]],
        shop_id: str = None,
        owner_id: int = None
    ) -> Dict[str, Any]:
        """
        Save extracted product Q&A pairs to knowledge base.
        
        Args:
            product_data: Product information
            qa_pairs: List of Q&A pairs
            shop_id: Shop identifier
            owner_id: Owner user ID
        
        Returns:
            dict with: success, saved_count, error
        """
        from apps.knowledge.models import KnowledgeBase
        from apps.ai.models import LearningRecord
        
        saved_count = 0
        errors = []
        
        # Build raw knowledge text for learning records
        raw_knowledge_parts = []
        if product_data.get('name'):
            raw_knowledge_parts.append(f"商品: {product_data['name']}")
        if product_data.get('price'):
            raw_knowledge_parts.append(f"价格: {product_data['price']}")
        if product_data.get('description'):
            raw_knowledge_parts.append(f"描述: {product_data['description'][:500]}")
        raw_knowledge = '\n'.join(raw_knowledge_parts)
        
        for qa in qa_pairs:
            try:
                from apps.knowledge.utils import infer_shop_id
                resolved_shop_id = infer_shop_id(owner_id=owner_id, shop_id=shop_id)
                KnowledgeBase.objects.create(
                    question=qa['question'],
                    answer=qa['answer'],
                    is_correct=True,  # AI-generated, mark as correct
                    shop_id=resolved_shop_id,
                    owner_id=owner_id,
                    source='ai_generated',
                    keywords=product_data.get('name', '')[:100]
                )
                saved_count += 1
                
                # Also save as learning record for training data
                try:
                    LearningRecord.objects.create(
                        record_type='qa_pair',
                        instruction=qa['question'],
                        response=qa['answer'],
                        product_name=product_data.get('name', '')[:255],
                        raw_knowledge=raw_knowledge,
                        shop_id=shop_id,
                        owner_id=owner_id,
                    )
                except Exception as lr_err:
                    logger.warning(f"Failed to save learning record: {lr_err}")
                    
            except Exception as e:
                errors.append(str(e))
                logger.error(f"Failed to save Q&A: {e}")
        
        # Save overall product knowledge as a learning record
        if product_data.get('description') and owner_id:
            try:
                LearningRecord.objects.create(
                    record_type='product_knowledge',
                    instruction=f"请介绍一下{product_data.get('name', '这个商品')}",
                    response=product_data.get('description', '')[:2000],
                    product_name=product_data.get('name', '')[:255],
                    raw_knowledge=raw_knowledge,
                    shop_id=shop_id,
                    owner_id=owner_id,
                )
            except Exception as pk_err:
                logger.warning(f"Failed to save product knowledge record: {pk_err}")
        
        return {
            'success': saved_count > 0,
            'saved_count': saved_count,
            'total_count': len(qa_pairs),
            'errors': errors
        }
