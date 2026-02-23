# -*- coding: utf-8 -*-
"""
URL routes for learning API.
"""
from django.urls import path
from .views import (
    StartLearningView,
    LearningTaskStatusView,
    UpdateTaskProgressView,
    ProcessProductView,
    CompleteTaskView,
    ResetAllTasksView,
)

urlpatterns = [
    path('start/', StartLearningView.as_view(), name='learning-start'),
    path('status/<str:task_id>/', LearningTaskStatusView.as_view(), name='learning-status'),
    path('progress/<str:task_id>/', UpdateTaskProgressView.as_view(), name='learning-progress'),
    path('process-product/', ProcessProductView.as_view(), name='learning-process-product'),
    path('complete/<str:task_id>/', CompleteTaskView.as_view(), name='learning-complete'),
    path('reset-all/', ResetAllTasksView.as_view(), name='learning-reset-all'),
]
