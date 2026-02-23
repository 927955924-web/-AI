"""
URL configuration for AI app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    GenerateReplyView,
    IdentifyIntentView,
    VisionAnalyzeView,
    VisionExtractView,
    VisionSessionView,
    VisionAnalyzePageView,
    SaveConversationView,
    SaveLearningRecordView,
    TrainingDataExportView,
    TrainingStatsView,
    KeywordRuleViewSet,
    SensitiveWordRuleViewSet,
    ScenarioRuleViewSet,
)

router = DefaultRouter()
router.register(r'keyword-rules', KeywordRuleViewSet, basename='keyword-rules')
router.register(r'sensitive-words', SensitiveWordRuleViewSet, basename='sensitive-words')
router.register(r'scenario-rules', ScenarioRuleViewSet, basename='scenario-rules')

urlpatterns = [
    path('generate-reply/', GenerateReplyView.as_view(), name='generate-reply'),
    path('identify-intent/', IdentifyIntentView.as_view(), name='identify-intent'),
    # Vision learning agent endpoints
    path('vision-analyze/', VisionAnalyzeView.as_view(), name='vision-analyze'),
    path('vision-extract/', VisionExtractView.as_view(), name='vision-extract'),
    path('vision-session/', VisionSessionView.as_view(), name='vision-session'),
    path('vision-analyze-page/', VisionAnalyzePageView.as_view(), name='vision-analyze-page'),
    # Conversation recording & training data
    path('save-conversation/', SaveConversationView.as_view(), name='save-conversation'),
    path('save-learning-record/', SaveLearningRecordView.as_view(), name='save-learning-record'),
    path('training-export/', TrainingDataExportView.as_view(), name='training-export'),
    path('training-stats/', TrainingStatsView.as_view(), name='training-stats'),
    # Rule management (router-based CRUD)
    path('', include(router.urls)),
]
