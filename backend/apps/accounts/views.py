"""
Views for accounts app.
"""
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .models import User
from .serializers import (
    UserSerializer,
    UserRegisterSerializer,
    UserLoginSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    VIPRenewSerializer,
)
from .models import SystemSettings


class RegisterView(generics.CreateAPIView):
    """User registration endpoint."""
    
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserRegisterSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'success': True,
            'data': {
                'user': UserSerializer(user).data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            },
            'message': '注册成功'
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """User login endpoint."""
    
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        # Update last login
        from django.utils import timezone
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'success': True,
            'data': {
                'user': UserSerializer(user).data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            },
            'message': '登录成功'
        })


class LogoutView(APIView):
    """User logout endpoint."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        
        return Response({
            'success': True,
            'message': '登出成功'
        })


class MeView(generics.RetrieveUpdateAPIView):
    """Get or update current user profile."""
    
    permission_classes = [IsAuthenticated]
    
    def get_object(self):
        return self.request.user
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return UserSerializer
        return UserUpdateSerializer
    
    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = UserSerializer(user)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = self.get_object()
        serializer = UserUpdateSerializer(user, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'success': True,
            'data': UserSerializer(user).data,
            'message': '更新成功'
        })


class ChangePasswordView(APIView):
    """Change password endpoint."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        
        return Response({
            'success': True,
            'message': '密码修改成功'
        })


class VIPRenewView(APIView):
    """Renew VIP status."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = VIPRenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        days = serializer.validated_data['days']
        user = request.user
        user.renew_vip(days)
        
        return Response({
            'success': True,
            'data': UserSerializer(user).data,
            'message': f'VIP续费成功，增加{days}天'
        })


class CustomTokenRefreshView(TokenRefreshView):
    """Custom token refresh view with consistent response format."""
    
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            return Response({
                'success': True,
                'data': {
                    'tokens': response.data
                }
            })
        return response


class ApiSettingsView(APIView):
    """Read/write API settings (LLM provider, API keys, etc.)."""

    permission_classes = [IsAuthenticated]

    # Settings keys managed by this view
    SETTING_KEYS = [
        'llm_provider', 'llm_model', 'llm_temperature', 'llm_base_url',
        'deepseek_api_key', 'qwen_api_key', 'doubao_api_key',
        'openai_api_key', 'gemini_api_key', 'kb_similarity_threshold',
    ]

    SECRET_KEYS = {
        'deepseek_api_key', 'qwen_api_key', 'doubao_api_key',
        'openai_api_key', 'gemini_api_key',
    }

    # Mapping from setting key to environment variable name
    ENV_MAPPING = {
        'llm_provider': 'LLM_PROVIDER',
        'llm_model': 'LLM_MODEL',
        'llm_temperature': 'LLM_TEMPERATURE',
        'llm_base_url': 'LLM_BASE_URL',
        'deepseek_api_key': 'DEEPSEEK_API_KEY',
        'qwen_api_key': 'QWEN_API_KEY',
        'doubao_api_key': 'DOUBAO_API_KEY',
        'openai_api_key': 'OPENAI_API_KEY',
        'gemini_api_key': 'GEMINI_API_KEY',
        'kb_similarity_threshold': 'KB_SIMILARITY_THRESHOLD',
    }

    def get(self, request):
        import os
        settings = {}
        
        # Load from SystemSettings database
        db_settings = {
            item.key: item.value
            for item in SystemSettings.objects.filter(key__in=self.SETTING_KEYS)
        }
        
        # Merge: DB takes priority, fallback to environment variables
        for key in self.SETTING_KEYS:
            value = db_settings.get(key)
            if not value and key in self.ENV_MAPPING:
                value = os.environ.get(self.ENV_MAPPING[key], '')
            
            if key in self.SECRET_KEYS and value:
                # Mask secret keys: show first 6 and last 4 chars
                if len(value) > 12:
                    settings[key] = value[:6] + '****' + value[-4:]
                else:
                    settings[key] = '****'
            else:
                settings[key] = value or ''
        
        return Response({'success': True, 'data': settings})

    def put(self, request):
        data = request.data
        updated = []
        for key in self.SETTING_KEYS:
            if key not in data:
                continue
            value = str(data[key]).strip()
            # Skip masked values (user didn't change the key)
            if key in self.SECRET_KEYS and '****' in value:
                continue
            is_secret = key in self.SECRET_KEYS
            SystemSettings.objects.update_or_create(
                key=key,
                defaults={'value': value, 'is_secret': is_secret},
            )
            updated.append(key)

        # Also update backend .env file for the running process
        self._sync_to_env(data)

        return Response({
            'success': True,
            'message': f'已保存 {len(updated)} 项设置',
            'data': {'updated_keys': updated},
        })

    def _sync_to_env(self, data):
        """Sync relevant settings to os.environ so the AI service picks them up."""
        import os
        for key, env_key in self.ENV_MAPPING.items():
            if key in data:
                value = str(data[key]).strip()
                if key in self.SECRET_KEYS and '****' in value:
                    continue
                if value:
                    os.environ[env_key] = value
