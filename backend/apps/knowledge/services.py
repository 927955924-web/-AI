"""
Knowledge base services including similarity matching.
"""
import json
import logging
from typing import List, Optional, Dict, Any
from django.db.models import Q, F
from .models import KnowledgeBase

logger = logging.getLogger(__name__)

try:
    from Levenshtein import ratio as levenshtein_ratio
except ImportError:
    # Fallback implementation if python-Levenshtein is not installed
    def levenshtein_ratio(s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        len1, len2 = len(s1), len(s2)
        if len1 < len2:
            s1, s2 = s2, s1
            len1, len2 = len2, len1
        current_row = range(len2 + 1)
        for i in range(len1):
            previous_row, current_row = current_row, [i + 1] + [0] * len2
            for j in range(len2):
                add, delete, change = previous_row[j + 1] + 1, current_row[j] + 1, previous_row[j]
                if s1[i] != s2[j]:
                    change += 1
                current_row[j + 1] = min(add, delete, change)
        distance = current_row[len2]
        return 1.0 - distance / max(len1, len2)


class EmbeddingService:
    """Service for generating and managing text embeddings."""
    
    _instance = None
    _model = None
    _model_name = 'paraphrase-multilingual-MiniLM-L12-v2'  # Good for Chinese
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if EmbeddingService._model is None:
            self._load_model()
    
    def _load_model(self):
        """Lazily load the sentence transformer model."""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"[Embedding] Loading model: {self._model_name}")
            EmbeddingService._model = SentenceTransformer(self._model_name)
            logger.info("[Embedding] Model loaded successfully")
        except ImportError:
            logger.warning("[Embedding] sentence-transformers not installed, vector search disabled")
            EmbeddingService._model = None
        except Exception as e:
            logger.error(f"[Embedding] Failed to load model: {e}")
            EmbeddingService._model = None
    
    @property
    def is_available(self) -> bool:
        return EmbeddingService._model is not None
    
    @property
    def model_name(self) -> str:
        return self._model_name
    
    def encode(self, text: str) -> Optional[List[float]]:
        """Encode text to embedding vector."""
        if not self.is_available or not text:
            return None
        try:
            embedding = EmbeddingService._model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"[Embedding] Encode error: {e}")
            return None
    
    def encode_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Encode multiple texts to embedding vectors."""
        if not self.is_available or not texts:
            return [None] * len(texts)
        try:
            embeddings = EmbeddingService._model.encode(texts, convert_to_numpy=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            logger.error(f"[Embedding] Batch encode error: {e}")
            return [None] * len(texts)
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2:
            return 0.0
        try:
            import numpy as np
            v1 = np.array(vec1)
            v2 = np.array(vec2)
            dot = np.dot(v1, v2)
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(dot / (norm1 * norm2))
        except Exception as e:
            logger.error(f"[Embedding] Cosine similarity error: {e}")
            return 0.0


class KnowledgeService:
    """Service for knowledge base operations."""
    
    def __init__(self, threshold: float = 0.7, use_vector_search: bool = True):
        self.threshold = threshold
        self.use_vector_search = use_vector_search
        self._embedding_service = None
    
    @property
    def embedding_service(self) -> EmbeddingService:
        """Lazy load embedding service."""
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService()
        return self._embedding_service
    
    def clean_text(self, text: str) -> str:
        """Clean text for matching."""
        import re
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text.strip().lower())
        text = re.sub(r'[，。！？、；：""''【】（）,.!?;:\'"]+', '', text)
        text = re.sub(r'[\[\]\{\}\(\)]+', '', text)
        return text
    
    def _vector_search(
        self,
        question: str,
        items: List[KnowledgeBase],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search on knowledge items."""
        if not self.embedding_service.is_available:
            return []
        
        # Encode the query
        query_embedding = self.embedding_service.encode(question)
        if not query_embedding:
            return []
        
        results = []
        for item in items:
            # Get or compute embedding
            if item.question_embedding:
                try:
                    item_embedding = json.loads(item.question_embedding)
                except json.JSONDecodeError:
                    continue
            else:
                # Compute and cache embedding
                item_embedding = self.embedding_service.encode(item.question)
                if item_embedding:
                    item.question_embedding = json.dumps(item_embedding)
                    item.embedding_model = self.embedding_service.model_name
                    item.save(update_fields=['question_embedding', 'embedding_model'])
                else:
                    continue
            
            # Calculate similarity
            similarity = self.embedding_service.cosine_similarity(query_embedding, item_embedding)
            
            if similarity >= self.threshold:
                results.append({
                    'id': item.id,
                    'question': item.question,
                    'answer': item.answer,
                    'is_correct': item.is_correct,
                    'similarity': similarity,
                    'usage_count': item.usage_count,
                    'search_method': 'vector',
                })
        
        # Sort by similarity descending
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:limit]
    
    def search_similar(
        self, 
        question: str, 
        shop_id: Optional[str] = None,
        owner_id: Optional[int] = None,
        product_ids: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar questions in the knowledge base.
        
        Uses a hybrid strategy:
        1. Try vector search first (if enabled and available)
        2. Fall back to keyword + Levenshtein matching
        3. Prioritize product-specific knowledge when product_ids provided
        
        Returns a list of matches with similarity scores.
        """
        cleaned_question = self.clean_text(question)
        if not cleaned_question:
            return []
        
        results = []
        seen_ids = set()
        
        # Build base query filters
        base_filters = Q()
        if shop_id:
            base_filters |= Q(shop_id=shop_id)
        if owner_id:
            base_filters |= Q(owner_id=owner_id)
        base_filters |= Q(shop__isnull=True, owner__isnull=True)
        
        # === Phase 1: Product-specific search (if product_ids provided) ===
        if product_ids:
            product_items = list(KnowledgeBase.objects.filter(product_id__in=product_ids)[:100])
            
            # Try vector search on product items first
            if self.use_vector_search and self.embedding_service.is_available and product_items:
                vector_results = self._vector_search(question, product_items, limit)
                for r in vector_results:
                    r['similarity'] += 0.05  # Boost for product match
                    results.append(r)
                    seen_ids.add(r['id'])
            
            # Keyword matches within product KB
            if len(results) < limit:
                product_keyword_matches = KnowledgeBase.objects.filter(
                    product_id__in=product_ids
                ).filter(
                    Q(question__icontains=question) | 
                    Q(keywords__icontains=question)
                ).exclude(id__in=seen_ids)
                
                for item in product_keyword_matches[:limit - len(results)]:
                    similarity = levenshtein_ratio(cleaned_question, self.clean_text(item.question))
                    results.append({
                        'id': item.id,
                        'question': item.question,
                        'answer': item.answer,
                        'is_correct': item.is_correct,
                        'similarity': max(similarity, 0.85),
                        'usage_count': item.usage_count,
                        'search_method': 'keyword',
                    })
                    seen_ids.add(item.id)
            
            # Levenshtein similarity on remaining product items
            if len(results) < limit:
                remaining_product_items = KnowledgeBase.objects.filter(
                    product_id__in=product_ids
                ).exclude(id__in=seen_ids)[:50]
                
                for item in remaining_product_items:
                    cleaned_item_question = self.clean_text(item.question)
                    similarity = levenshtein_ratio(cleaned_question, cleaned_item_question)
                    
                    if similarity >= self.threshold * 0.85:
                        results.append({
                            'id': item.id,
                            'question': item.question,
                            'answer': item.answer,
                            'is_correct': item.is_correct,
                            'similarity': similarity + 0.05,
                            'usage_count': item.usage_count,
                            'search_method': 'levenshtein',
                        })
                        seen_ids.add(item.id)
                        
                        if len(results) >= limit:
                            break
        
        # === Phase 2: General shop search ===
        if len(results) < limit:
            general_items = KnowledgeBase.objects.filter(base_filters).exclude(id__in=seen_ids)
            
            # Try vector search on general items
            if self.use_vector_search and self.embedding_service.is_available:
                general_items_list = list(general_items[:200])
                vector_results = self._vector_search(question, general_items_list, limit - len(results))
                for r in vector_results:
                    if r['id'] not in seen_ids:
                        results.append(r)
                        seen_ids.add(r['id'])
            
            # Keyword matches
            if len(results) < limit:
                keyword_matches = general_items.filter(
                    Q(question__icontains=question) | 
                    Q(keywords__icontains=question)
                ).exclude(id__in=seen_ids)
                
                for item in keyword_matches[:limit - len(results)]:
                    similarity = levenshtein_ratio(cleaned_question, self.clean_text(item.question))
                    results.append({
                        'id': item.id,
                        'question': item.question,
                        'answer': item.answer,
                        'is_correct': item.is_correct,
                        'similarity': max(similarity, 0.8),
                        'usage_count': item.usage_count,
                        'search_method': 'keyword',
                    })
                    seen_ids.add(item.id)
            
            # Levenshtein similarity on remaining items
            if len(results) < limit:
                remaining_items = general_items.exclude(id__in=seen_ids)[:100]
                for item in remaining_items:
                    cleaned_item_question = self.clean_text(item.question)
                    similarity = levenshtein_ratio(cleaned_question, cleaned_item_question)
                    
                    if similarity >= self.threshold:
                        results.append({
                            'id': item.id,
                            'question': item.question,
                            'answer': item.answer,
                            'is_correct': item.is_correct,
                            'similarity': similarity,
                            'usage_count': item.usage_count,
                            'search_method': 'levenshtein',
                        })
                        
                        if len(results) >= limit:
                            break
        
        # Sort by: is_correct (desc), similarity (desc), usage_count (desc)
        results.sort(key=lambda x: (x['is_correct'], x['similarity'], x['usage_count']), reverse=True)
        
        return results[:limit]
    
    def get_best_answer(
        self, 
        question: str, 
        shop_id: Optional[str] = None,
        owner_id: Optional[int] = None,
        product_ids: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the best matching answer for a question.
        
        Returns the best match if found, prioritizing correct answers.
        """
        results = self.search_similar(question, shop_id, owner_id, product_ids=product_ids, limit=3)
        
        if not results:
            return None
        
        # Prioritize correct answers
        for result in results:
            if result['is_correct']:
                # Increment usage count
                KnowledgeBase.objects.filter(id=result['id']).update(
                    usage_count=F('usage_count') + 1
                )
                return result
        
        # Return highest similarity if no correct answer
        best = results[0]
        if best['similarity'] >= self.threshold:
            KnowledgeBase.objects.filter(id=best['id']).update(
                usage_count=F('usage_count') + 1
            )
            return best
        
        return None
    
    def add_qa(
        self, 
        question: str, 
        answer: str, 
        is_correct: bool = False,
        shop_id: Optional[str] = None,
        owner_id: Optional[int] = None,
        category: str = '',
        keywords: str = ''
    ) -> KnowledgeBase:
        """Add a new Q&A pair to the knowledge base with embedding."""
        # Generate embedding for the question
        embedding = None
        embedding_model = ''
        if self.use_vector_search and self.embedding_service.is_available:
            embedding = self.embedding_service.encode(question)
            embedding_model = self.embedding_service.model_name
        
        return KnowledgeBase.objects.create(
            question=question,
            answer=answer,
            is_correct=is_correct,
            shop_id=shop_id,
            owner_id=owner_id,
            category=category,
            keywords=keywords,
            question_embedding=json.dumps(embedding) if embedding else None,
            embedding_model=embedding_model,
        )
    
    def backfill_embeddings(self, batch_size: int = 100) -> Dict[str, int]:
        """Backfill embeddings for existing knowledge base entries without embeddings."""
        if not self.embedding_service.is_available:
            return {'processed': 0, 'skipped': 0, 'error': 'Embedding service not available'}
        
        items_without_embedding = KnowledgeBase.objects.filter(
            Q(question_embedding__isnull=True) | Q(question_embedding='')
        )
        
        total = items_without_embedding.count()
        processed = 0
        errors = 0
        
        logger.info(f"[Embedding] Starting backfill for {total} items")
        
        for item in items_without_embedding.iterator():
            try:
                embedding = self.embedding_service.encode(item.question)
                if embedding:
                    item.question_embedding = json.dumps(embedding)
                    item.embedding_model = self.embedding_service.model_name
                    item.save(update_fields=['question_embedding', 'embedding_model'])
                    processed += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"[Embedding] Error processing item {item.id}: {e}")
                errors += 1
            
            if processed % batch_size == 0:
                logger.info(f"[Embedding] Processed {processed}/{total}")
        
        logger.info(f"[Embedding] Backfill complete: {processed} processed, {errors} errors")
        return {'processed': processed, 'errors': errors, 'total': total}
    
    def get_daily_summary(self, owner_id: Optional[int] = None) -> Dict[str, Any]:
        """Get daily learning summary."""
        from django.utils import timezone
        from datetime import timedelta
        
        today = timezone.now().date()
        start_of_day = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )
        
        filters = Q(created_at__gte=start_of_day)
        if owner_id:
            filters &= Q(owner_id=owner_id)
        
        items = KnowledgeBase.objects.filter(filters)
        total = items.count()
        correct = items.filter(is_correct=True).count()
        
        return {
            'date': today.isoformat(),
            'total_questions': total,
            'correct_answers': correct,
            'accuracy_rate': correct / total if total > 0 else 0,
        }
