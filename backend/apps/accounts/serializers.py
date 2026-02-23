"""
Serializers for accounts app.
"""
from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details."""
    
    class Meta:
        model = User
        fields = [
            'id', 'user_id', 'username', 'email', 'phone', 'role',
            'vip_status', 'vip_expiry', 'invite_code', 'created_at', 'last_login'
        ]
        read_only_fields = ['id', 'user_id', 'invite_code', 'created_at', 'last_login']


class UserRegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    
    password = serializers.CharField(
        write_only=True, 
        required=True, 
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password2 = serializers.CharField(
        write_only=True, 
        required=True,
        style={'input_type': 'password'}
    )
    invite_code = serializers.CharField(
        write_only=True, 
        required=False, 
        allow_blank=True
    )
    
    class Meta:
        model = User
        fields = [
            'username', 'email', 'phone', 'password', 'password2', 'invite_code'
        ]
    
    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password2'):
            raise serializers.ValidationError({'password2': '两次密码不一致'})
        
        # Validate invite code if provided
        invite_code_input = attrs.pop('invite_code', None)
        if invite_code_input:
            try:
                inviter = User.objects.get(invite_code=invite_code_input)
                attrs['invited_by'] = inviter
            except User.DoesNotExist:
                raise serializers.ValidationError({'invite_code': '邀请码无效'})
        
        attrs.pop('password2', None)
        return attrs
    
    def create(self, validated_data):
        invited_by = validated_data.pop('invited_by', None)
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            phone=validated_data.get('phone', ''),
            password=validated_data['password'],
        )
        if invited_by:
            user.invited_by = invited_by
            user.save(update_fields=['invited_by'])
        return user


class UserLoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    
    username = serializers.CharField(required=True)
    password = serializers.CharField(
        required=True, 
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            # Try to authenticate with username or phone
            user = authenticate(username=username, password=password)
            
            if not user:
                # Try with phone number
                try:
                    user_obj = User.objects.get(phone=username)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass
            
            if not user:
                raise serializers.ValidationError('用户名或密码错误')
            
            if not user.is_active:
                raise serializers.ValidationError('用户已被禁用')
            
            attrs['user'] = user
        else:
            raise serializers.ValidationError('请提供用户名和密码')
        
        return attrs


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile."""
    
    class Meta:
        model = User
        fields = ['email', 'phone']
    
    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('该手机号已被使用')
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password."""
    
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True, 
        write_only=True,
        validators=[validate_password]
    )
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('当前密码错误')
        return value


class VIPRenewSerializer(serializers.Serializer):
    """Serializer for VIP renewal."""
    
    days = serializers.IntegerField(min_value=1, max_value=365, required=True)
