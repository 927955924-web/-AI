from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ai'
    verbose_name = 'AI服务'

    def ready(self):
        """Start model health check thread when app is ready."""
        import os
        # Only start in the main process, not in management commands
        if os.environ.get('RUN_MAIN') == 'true':
            from .services import start_model_health_check_thread
            start_model_health_check_thread()
