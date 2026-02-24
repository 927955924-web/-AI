from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ai'
    verbose_name = 'AI服务'

    def ready(self):
        """Start background services when app is ready."""
        import os
        # Start in Django dev server main process or production gunicorn
        is_dev_main = os.environ.get('RUN_MAIN') == 'true'
        is_production = os.environ.get('DJANGO_SETTINGS_MODULE') == 'config.settings.production'

        if is_dev_main or is_production:
            from .services import start_model_health_check_thread
            start_model_health_check_thread()

            # Start daily conversation analysis scheduler
            from .scheduler import start_daily_analysis_scheduler
            start_daily_analysis_scheduler()
