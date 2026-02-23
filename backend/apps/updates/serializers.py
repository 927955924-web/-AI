from rest_framework import serializers
from .models import ClientVersion


class ClientVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientVersion
        fields = [
            'id', 'version', 'platform', 'file_name', 'file_size',
            'download_url', 'checksum_sha512', 'release_notes',
            'is_latest', 'created_at', 'download_count',
        ]
        read_only_fields = ['id', 'created_at', 'download_count']
