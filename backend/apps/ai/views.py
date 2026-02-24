"""
Views for AI app.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

import json
import logging

from django.core.cache import cache
from django.db.models import Q
from core.utils import md5_hash
from .services import AIService
from .models import ConversationRecord, LearningRecord, KeywordRule, SensitiveWordRule, ScenarioRule
from .serializers import (
    GenerateReplySerializer,
    IdentifyIntentSerializer,
    VisionAnalyzeSerializer,
    VisionExtractSerializer,
    SaveConversationSerializer,
    SaveLearningRecordSerializer,
    TrainingExportSerializer,
    KeywordRuleSerializer,
    SensitiveWordRuleSerializer,
    ScenarioRuleSerializer,
)
from .vision_agent import VisionLearningAgent, VisionAgentManager

logger = logging.getLogger(__name__)


class GenerateReplyView(APIView):
    """Generate AI reply using knowledge-base-first strategy."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = GenerateReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        question = serializer.validated_data['question']
        context = serializer.validated_data.get('context')
        shop_id = serializer.validated_data.get('shop_id')
        order_detail = serializer.validated_data.get('order_detail')
        model = serializer.validated_data.get('model')
        product_names = serializer.validated_data.get('product_names', [])
        product_card_ids = serializer.validated_data.get('product_card_ids', [])
        buyer_images = serializer.validated_data.get('buyer_images', [])
        buyer_video_frames = serializer.validated_data.get('buyer_video_frames', [])
        
        service = AIService()
        
        # If buyer sent images, analyze them with vision model
        image_analysis = None
        if buyer_images:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[VisionAnalysis] Analyzing {len(buyer_images)} buyer images...")
            
            image_descriptions = []
            for i, image_url in enumerate(buyer_images[:3]):  # Limit to 3 images
                try:
                    # Check cache first
                    image_hash = md5_hash(image_url)
                    cache_key = f"img_desc:{image_hash}"
                    cached_desc = cache.get(cache_key)
                    if cached_desc:
                        image_descriptions.append(f"图片{i+1}: {cached_desc}")
                        logger.info(f"[VisionAnalysis] Image {i+1} using cached result: {cached_desc[:80]}...")
                        continue
                    
                    # Fetch image and convert to base64
                    import requests
                    import base64
                    
                    response = requests.get(image_url, timeout=10)
                    if response.status_code == 200:
                        image_base64 = base64.b64encode(response.content).decode('utf-8')
                        
                        # Analyze image with vision model
                        prompt = """请分析这张买家发送的图片，描述图片内容。
如果是商品图片，请详细描述商品特征，包括图片上的所有文字标注（如型号、规格、支持的功能等）。
如果是问题反馈图片（如损坏、质量问题），请描述具体问题。
如果是截图或文字图片，请完整识别其中的文字内容。
如果图片模糊或无法确定某些信息，请明确说明'无法确认'，不要猜测。
请用简洁的中文回答。"""
                        
                        result = service.call_vision_model(prompt, image_base64)
                        if result['success'] and result['content']:
                            # Cache the result for 7 days
                            cache.set(cache_key, result['content'], 7 * 86400)
                            image_descriptions.append(f"图片{i+1}: {result['content']}")
                            logger.info(f"[VisionAnalysis] Image {i+1} analyzed and cached: {result['content'][:100]}...")
                        else:
                            logger.warning(f"[VisionAnalysis] Image {i+1} analysis failed: {result.get('error')}")
                    else:
                        logger.warning(f"[VisionAnalysis] Failed to fetch image {i+1}: HTTP {response.status_code}")
                except Exception as e:
                    logger.error(f"[VisionAnalysis] Error analyzing image {i+1}: {e}")
            
            if image_descriptions:
                image_analysis = "【买家发送的图片内容】\n" + "\n".join(image_descriptions)
                logger.info(f"[VisionAnalysis] Total analysis: {image_analysis[:200]}...")
        
        # If buyer sent video frames, analyze them with vision model
        video_analysis = None
        if buyer_video_frames:
            logger.info(f"[VisionAnalysis] Analyzing {len(buyer_video_frames)} video frames...")
            
            frame_descriptions = []
            for i, frame in enumerate(buyer_video_frames[:5]):  # Limit to 5 frames
                try:
                    frame_base64 = frame.get('base64', '')
                    timestamp = frame.get('timestamp', 0)
                    
                    if not frame_base64 or len(frame_base64) < 100:
                        continue
                    
                    # Check cache
                    import hashlib
                    frame_hash = hashlib.md5(frame_base64[:200].encode()).hexdigest()
                    cache_key = f"vid_frame_desc:{frame_hash}"
                    cached_desc = cache.get(cache_key)
                    if cached_desc:
                        frame_descriptions.append(f"视频{timestamp}s: {cached_desc}")
                        logger.info(f"[VisionAnalysis] Video frame {i+1} using cached result")
                        continue
                    
                    prompt = """请分析这个视频帧截图，描述画面内容。
如果是商品展示，请详细描述商品外观、特征和画面上的文字标注。
如果是使用演示，请描述操作步骤。
如果是问题反馈（如产品损坏），请描述具体问题。
如果画面模糊或无法确定某些信息，请明确说明'无法确认'，不要猜测。
请用简洁的中文回答。"""
                    
                    result = service.call_vision_model(prompt, frame_base64)
                    if result['success'] and result['content']:
                        cache.set(cache_key, result['content'], 7 * 86400)
                        frame_descriptions.append(f"视频{timestamp}s: {result['content']}")
                        logger.info(f"[VisionAnalysis] Video frame {i+1} at {timestamp}s analyzed: {result['content'][:80]}...")
                    else:
                        logger.warning(f"[VisionAnalysis] Video frame {i+1} analysis failed: {result.get('error')}")
                except Exception as e:
                    logger.error(f"[VisionAnalysis] Error analyzing video frame {i+1}: {e}")
            
            if frame_descriptions:
                video_analysis = "【买家发送的视频内容】\n" + "\n".join(frame_descriptions)
                logger.info(f"[VisionAnalysis] Video analysis: {video_analysis[:200]}...")
        
        # Add image analysis and video analysis to context if available
        enhanced_context = context or ''
        if image_analysis:
            enhanced_context = f"{enhanced_context}\n\n{image_analysis}" if enhanced_context else image_analysis
        if video_analysis:
            enhanced_context = f"{enhanced_context}\n\n{video_analysis}" if enhanced_context else video_analysis
        
        result = service.generate_reply(
            question=question,
            context=enhanced_context,
            order_detail=order_detail,
            shop_id=shop_id,
            owner_id=request.user.id,
            model=model,
            product_names=product_names,
            product_card_ids=product_card_ids,
            buyer_image_urls=buyer_images or [],
        )
        
        return Response({
            'success': True,
            'data': result
        })


class IdentifyIntentView(APIView):
    """Identify user intent from a message."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = IdentifyIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        message = serializer.validated_data['message']
        
        service = AIService()
        result = service.identify_intent(message)
        
        return Response({
            'success': True,
            'data': result
        })


class VisionAnalyzeView(APIView):
    """
    Analyze page screenshot using vision language model.
    
    POST /api/v1/ai/vision-analyze/
    
    Request body:
        - image_base64: Base64 encoded screenshot
        - page_type: 'list' or 'detail'
        - session_id: Optional session ID for tracking
        - model: Vision model to use (default: doubao-vision)
    
    Returns:
        - success: bool
        - action: 'click', 'scroll', 'extract', 'back', or 'done'
        - data: Action-specific data (target info, extracted product info, etc.)
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = VisionAnalyzeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        image_base64 = serializer.validated_data['image_base64']
        page_type = serializer.validated_data.get('page_type', 'list')
        session_id = serializer.validated_data.get('session_id') or str(request.user.id)
        model = serializer.validated_data.get('model', 'doubao-vision')
        
        # Get or create agent for this session
        agent = VisionAgentManager.get_agent(session_id, model=model)
        
        # Analyze the page
        result = agent.analyze_page(
            image_base64=image_base64,
            page_type=page_type
        )
        
        return Response({
            'success': result['success'],
            'action': result.get('action'),
            'data': result.get('data'),
            'error': result.get('error'),
            'model_used': result.get('model_used'),
            'session_summary': agent.get_session_summary()
        })


class VisionExtractView(APIView):
    """
    Process extracted product data and optionally save to knowledge base.
    
    POST /api/v1/ai/vision-extract/
    
    Request body:
        - extraction_data: Product information from vision analysis
        - session_id: Session ID
        - shop_id: Shop identifier
        - save_to_kb: Whether to save Q&A pairs to knowledge base (default: true)
    
    Returns:
        - success: bool
        - product_data: Processed product information
        - qa_pairs: Generated Q&A pairs
        - saved_count: Number of Q&A pairs saved to knowledge base
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = VisionExtractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        extraction_data = serializer.validated_data['extraction_data']
        session_id = serializer.validated_data.get('session_id') or str(request.user.id)
        shop_id = serializer.validated_data.get('shop_id')
        save_to_kb = serializer.validated_data.get('save_to_kb', True)
        
        # Get agent for this session
        agent = VisionAgentManager.get_agent(session_id)
        
        # Process extraction result
        result = agent.process_extraction_result(extraction_data)
        
        response_data = {
            'success': result['success'],
            'product_data': result.get('product_data'),
            'qa_pairs': result.get('qa_pairs', []),
            'error': result.get('error'),
        }
        
        # Save to knowledge base if requested
        if result['success'] and save_to_kb and result.get('qa_pairs'):
            save_result = VisionAgentManager.save_to_knowledge_base(
                product_data=result['product_data'],
                qa_pairs=result['qa_pairs'],
                shop_id=shop_id,
                owner_id=request.user.id
            )
            response_data['saved_count'] = save_result['saved_count']
            response_data['save_errors'] = save_result.get('errors', [])
        
        response_data['session_summary'] = agent.get_session_summary()
        
        return Response(response_data)


class VisionSessionView(APIView):
    """
    Manage vision learning sessions.
    
    GET /api/v1/ai/vision-session/
        Get current session status
    
    DELETE /api/v1/ai/vision-session/
        End and cleanup session
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        session_id = request.query_params.get('session_id') or str(request.user.id)
        
        try:
            agent = VisionAgentManager.get_agent(session_id)
            return Response({
                'success': True,
                'session_id': session_id,
                'summary': agent.get_session_summary(),
                'can_continue': agent.should_continue()
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request):
        session_id = request.query_params.get('session_id') or str(request.user.id)
        
        try:
            agent = VisionAgentManager.get_agent(session_id)
            summary = agent.get_session_summary()
            VisionAgentManager.remove_agent(session_id)
            
            return Response({
                'success': True,
                'session_id': session_id,
                'final_summary': summary,
                'message': 'Session ended successfully'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class VisionAnalyzePageView(APIView):
    """
    Analyze product detail page screenshot using vision model.
    Extracts product information including text in images.
    
    POST /api/v1/ai/vision-analyze-page/
    
    Request body:
        - image_base64: Base64 encoded page screenshot
        - page_type: 'product_detail' (default)
        - extract_mode: 'full' for comprehensive extraction
    
    Returns:
        - success: bool
        - description: Full product description including image content
        - specs: Extracted specifications
        - images: Image URLs found
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        image_base64 = request.data.get('image_base64')
        page_type = request.data.get('page_type', 'product_detail')
        extract_mode = request.data.get('extract_mode', 'full')
        
        if not image_base64:
            return Response({
                'success': False,
                'error': '缺少图片数据'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Build prompt for vision model
        prompt = """你是一个电商商品信息提取助手。请仔细分析这个商品详情页面的截图。

任务：提取页面中所有可见的商品信息，包括：
1. 商品名称/标题
2. 商品价格和库存信息
3. 商品规格参数（如颜色、尺寸、型号等）
4. 商品详情描述（重要：仔细阅读图片中的文字说明）
5. 产品特点和卖点
6. 服务承诺（如发货时间、售后保障等）
7. 图片中展示的产品使用方法、安装说明等

请特别注意：
- 仔细识别图片中的文字内容，这些往往包含重要的产品信息
- 提取产品的技术参数和使用说明
- 识别产品的包装内容物说明

请按以下JSON格式返回提取的信息：
{
    "title": "商品名称",
    "price": "价格信息",
    "stock": "库存信息",
    "specs": {
        "规格名1": "规格值1",
        "规格名2": "规格值2"
    },
    "description": "商品的完整描述，包括从图片中提取的所有文字信息",
    "features": ["产品特点1", "产品特点2"],
    "services": "服务承诺信息",
    "usage_instructions": "使用方法或安装说明（如果图片中有）",
    "package_contents": "包装内容物（如果图片中有展示）"
}

只返回JSON，不要有其他文字。"""
        
        try:
            service = AIService()
            result = service.call_vision_model(prompt, image_base64)
            
            if not result['success']:
                return Response({
                    'success': False,
                    'error': result['error']
                })
            
            # Parse JSON response
            import json
            import re
            
            content = result['content']
            
            # Extract JSON from potential markdown code blocks
            if '```' in content:
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if json_match:
                    content = json_match.group(1)
            
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # If JSON parsing fails, use raw content as description
                data = {
                    'description': content,
                    'specs': {},
                    'features': []
                }
            
            # Build comprehensive description
            description_parts = []
            if data.get('title'):
                description_parts.append(f"商品名称: {data['title']}")
            if data.get('price'):
                description_parts.append(f"价格: {data['price']}")
            if data.get('stock'):
                description_parts.append(f"库存: {data['stock']}")
            if data.get('specs'):
                description_parts.append("\n规格参数:")
                for k, v in data['specs'].items():
                    description_parts.append(f"  - {k}: {v}")
            if data.get('features'):
                description_parts.append("\n产品特点:")
                for f in data['features']:
                    description_parts.append(f"  - {f}")
            if data.get('services'):
                description_parts.append(f"\n服务承诺: {data['services']}")
            if data.get('usage_instructions'):
                description_parts.append(f"\n使用说明: {data['usage_instructions']}")
            if data.get('package_contents'):
                description_parts.append(f"\n包装内容: {data['package_contents']}")
            if data.get('description'):
                description_parts.append(f"\n商品详情:\n{data['description']}")
            
            full_description = '\n'.join(description_parts)
            
            return Response({
                'success': True,
                'description': full_description,
                'specs': data.get('specs', {}),
                'images': [],
                'raw_data': data
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SaveConversationView(APIView):
    """
    Save a buyer-customer dialogue record for future model training.
    
    POST /api/v1/ai/save-conversation/
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = SaveConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        shop_id = data.get('shop_id')
        
        record = ConversationRecord.objects.create(
            buyer_message=data['buyer_message'],
            customer_reply=data['customer_reply'],
            conversation_context=data.get('conversation_context', ''),
            buyer_name=data.get('buyer_name', ''),
            image_analysis=data.get('image_analysis', ''),
            order_info=data.get('order_info', ''),
            shop_id=shop_id if shop_id else None,
            owner=request.user,
            platform=data.get('platform', ''),
            source=data.get('source', 'ai_auto'),
            model_used=data.get('model_used', ''),
            confidence=data.get('confidence', 0.0),
        )
        
        logger.info(f"[ConvRecord] Saved conversation #{record.id}: "
                     f"Q={data['buyer_message'][:50]}... source={data.get('source')}")
        
        return Response({
            'success': True,
            'record_id': record.id,
        })


class SaveLearningRecordView(APIView):
    """
    Save a learning record (product knowledge / Q&A pair) for future model training.
    
    POST /api/v1/ai/save-learning-record/
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        # Support batch saving
        records_data = request.data.get('records')
        if records_data and isinstance(records_data, list):
            return self._save_batch(request, records_data)
        
        serializer = SaveLearningRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        shop_id = data.get('shop_id')
        
        record = LearningRecord.objects.create(
            record_type=data.get('record_type', 'product_knowledge'),
            instruction=data['instruction'],
            response=data['response'],
            product_name=data.get('product_name', ''),
            raw_knowledge=data.get('raw_knowledge', ''),
            shop_id=shop_id if shop_id else None,
            owner=request.user,
        )
        
        logger.info(f"[LearningRecord] Saved #{record.id}: type={record.record_type}, "
                     f"product={data.get('product_name', '')[:30]}")
        
        return Response({
            'success': True,
            'record_id': record.id,
        })
    
    def _save_batch(self, request, records_data):
        """Save multiple learning records at once."""
        saved = []
        errors = []
        
        for i, item in enumerate(records_data):
            try:
                serializer = SaveLearningRecordSerializer(data=item)
                serializer.is_valid(raise_exception=True)
                data = serializer.validated_data
                shop_id = data.get('shop_id')
                
                record = LearningRecord.objects.create(
                    record_type=data.get('record_type', 'product_knowledge'),
                    instruction=data['instruction'],
                    response=data['response'],
                    product_name=data.get('product_name', ''),
                    raw_knowledge=data.get('raw_knowledge', ''),
                    shop_id=shop_id if shop_id else None,
                    owner=request.user,
                )
                saved.append(record.id)
            except Exception as e:
                errors.append(f"Record {i}: {str(e)}")
        
        logger.info(f"[LearningRecord] Batch saved {len(saved)} records, {len(errors)} errors")
        
        return Response({
            'success': True,
            'saved_count': len(saved),
            'saved_ids': saved,
            'errors': errors,
        })


class TrainingDataExportView(APIView):
    """
    Export collected conversation and learning data as training dataset.
    
    POST /api/v1/ai/training-export/
    
    Supports formats:
    - alpaca: {"instruction": "...", "input": "...", "output": "..."}
    - sharegpt: {"conversations": [{"from": "human", "value": "..."}, ...]}
    - jsonl: one JSON object per line
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = TrainingExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        shop_id = data.get('shop_id')
        fmt = data.get('format', 'alpaca')
        quality_filter = data.get('quality_filter', 'all')
        include_learning = data.get('include_learning', True)
        include_conversations = data.get('include_conversations', True)
        
        training_data = []
        
        # Collect conversation records
        if include_conversations:
            conv_qs = ConversationRecord.objects.filter(owner=request.user)
            if shop_id:
                conv_qs = conv_qs.filter(shop_id=shop_id)
            if quality_filter == 'approved':
                conv_qs = conv_qs.filter(quality='approved')
            elif quality_filter == 'unverified_and_approved':
                conv_qs = conv_qs.filter(quality__in=['unverified', 'approved'])
            
            for conv in conv_qs:
                entry = self._format_conversation(conv, fmt)
                if entry:
                    training_data.append(entry)
        
        # Collect learning records
        if include_learning:
            learn_qs = LearningRecord.objects.filter(owner=request.user)
            if shop_id:
                learn_qs = learn_qs.filter(shop_id=shop_id)
            
            for lr in learn_qs:
                entry = self._format_learning(lr, fmt)
                if entry:
                    training_data.append(entry)
        
        # Mark as exported
        if include_conversations:
            conv_qs.update(exported=True)
        if include_learning:
            learn_qs.update(exported=True)
        
        # Build stats
        stats = {
            'total_records': len(training_data),
            'conversation_count': conv_qs.count() if include_conversations else 0,
            'learning_count': learn_qs.count() if include_learning else 0,
            'format': fmt,
        }
        
        return Response({
            'success': True,
            'data': training_data,
            'stats': stats,
        })
    
    def _format_conversation(self, conv, fmt):
        """Format a conversation record for training."""
        system_prompt = "你是一名专业的电商客服，请根据买家的问题给出专业、准确、热情的回复。"
        
        context_parts = []
        if conv.conversation_context:
            context_parts.append(conv.conversation_context)
        if conv.image_analysis:
            context_parts.append(conv.image_analysis)
        if conv.order_info:
            context_parts.append(f"订单信息: {conv.order_info}")
        context = "\n".join(context_parts)
        
        if fmt == 'alpaca':
            return {
                "instruction": conv.buyer_message,
                "input": context,
                "output": conv.customer_reply,
                "system": system_prompt,
            }
        elif fmt == 'sharegpt':
            conversations = [{"from": "system", "value": system_prompt}]
            if context:
                conversations.append({"from": "human", "value": f"[上下文] {context}\n\n{conv.buyer_message}"})
            else:
                conversations.append({"from": "human", "value": conv.buyer_message})
            conversations.append({"from": "gpt", "value": conv.customer_reply})
            return {"conversations": conversations}
        else:  # jsonl
            return {
                "system": system_prompt,
                "question": conv.buyer_message,
                "context": context,
                "answer": conv.customer_reply,
                "source": conv.source,
                "quality": conv.quality,
            }
    
    def _format_learning(self, lr, fmt):
        """Format a learning record for training."""
        system_prompt = "你是一名专业的电商客服，请根据买家的问题给出专业、准确、热情的回复。"
        
        if fmt == 'alpaca':
            return {
                "instruction": lr.instruction,
                "input": lr.raw_knowledge[:500] if lr.raw_knowledge else "",
                "output": lr.response,
                "system": system_prompt,
            }
        elif fmt == 'sharegpt':
            conversations = [{"from": "system", "value": system_prompt}]
            conversations.append({"from": "human", "value": lr.instruction})
            conversations.append({"from": "gpt", "value": lr.response})
            return {"conversations": conversations}
        else:  # jsonl
            return {
                "system": system_prompt,
                "question": lr.instruction,
                "context": lr.raw_knowledge[:500] if lr.raw_knowledge else "",
                "answer": lr.response,
                "source": "learning",
                "type": lr.record_type,
            }


class TrainingStatsView(APIView):
    """
    Get statistics about collected training data.
    
    GET /api/v1/ai/training-stats/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        shop_id = request.query_params.get('shop_id')
        
        conv_qs = ConversationRecord.objects.filter(owner=request.user)
        learn_qs = LearningRecord.objects.filter(owner=request.user)
        
        if shop_id:
            conv_qs = conv_qs.filter(shop_id=shop_id)
            learn_qs = learn_qs.filter(shop_id=shop_id)
        
        return Response({
            'success': True,
            'data': {
                'conversations': {
                    'total': conv_qs.count(),
                    'ai_auto': conv_qs.filter(source='ai_auto').count(),
                    'ai_kb': conv_qs.filter(source='ai_kb').count(),
                    'human_edited': conv_qs.filter(source='human_edited').count(),
                    'debug_edited': conv_qs.filter(source='debug_edited').count(),
                    'approved': conv_qs.filter(quality='approved').count(),
                    'rejected': conv_qs.filter(quality='rejected').count(),
                    'exported': conv_qs.filter(exported=True).count(),
                },
                'learning_records': {
                    'total': learn_qs.count(),
                    'product_knowledge': learn_qs.filter(record_type='product_knowledge').count(),
                    'qa_pair': learn_qs.filter(record_type='qa_pair').count(),
                    'image_description': learn_qs.filter(record_type='image_description').count(),
                    'exported': learn_qs.filter(exported=True).count(),
                },
                'total_training_ready': conv_qs.exclude(quality='rejected').count() + learn_qs.count(),
            }
        })


class KeywordRuleViewSet(ModelViewSet):
    """CRUD ViewSet for keyword trigger rules."""
    
    serializer_class = KeywordRuleSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        qs = KeywordRule.objects.filter(owner=self.request.user)
        shop_id = self.request.query_params.get('shop_id')
        if shop_id:
            qs = qs.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        return qs
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class SensitiveWordRuleViewSet(ModelViewSet):
    """CRUD ViewSet for sensitive word filtering rules."""
    
    serializer_class = SensitiveWordRuleSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        qs = SensitiveWordRule.objects.filter(owner=self.request.user)
        shop_id = self.request.query_params.get('shop_id')
        if shop_id:
            qs = qs.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        return qs
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ScenarioRuleViewSet(ModelViewSet):
    """CRUD ViewSet for scenario monitoring rules."""
    
    serializer_class = ScenarioRuleSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        qs = ScenarioRule.objects.filter(owner=self.request.user)
        shop_id = self.request.query_params.get('shop_id')
        if shop_id:
            qs = qs.filter(Q(shop_id=shop_id) | Q(shop__isnull=True))
        return qs
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
