"""
Views for updates app - Client version management APIs.
"""
from packaging.version import Version, InvalidVersion
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from django.http import HttpResponse

from .models import ClientVersion
from .serializers import ClientVersionSerializer


class CheckUpdateView(APIView):
    """Check if a newer client version is available."""

    permission_classes = [AllowAny]

    def get(self, request):
        current_version = request.GET.get('current_version', '0.0.0')
        platform = request.GET.get('platform', 'windows')

        latest = ClientVersion.objects.filter(
            platform=platform,
            is_latest=True,
        ).first()

        if not latest:
            return Response({
                'success': True,
                'data': {'has_update': False}
            })

        try:
            has_update = Version(latest.version) > Version(current_version)
        except InvalidVersion:
            has_update = latest.version != current_version

        data = {'has_update': has_update}
        if has_update:
            data.update({
                'latest_version': latest.version,
                'current_version': current_version,
                'release_notes': latest.release_notes,
                'download_url': latest.download_url,
                'file_name': latest.file_name,
                'file_size': latest.file_size,
                'checksum_sha512': latest.checksum_sha512,
            })

        return Response({'success': True, 'data': data})


class LatestYmlView(APIView):
    """Return latest.yml manifest for electron-updater generic provider."""

    permission_classes = [AllowAny]

    def get(self, request):
        platform = request.GET.get('platform', 'windows')

        latest = ClientVersion.objects.filter(
            platform=platform,
            is_latest=True,
        ).first()

        if not latest:
            return Response(
                {'error': 'No version available'},
                status=status.HTTP_404_NOT_FOUND,
            )

        yml_content = (
            f"version: {latest.version}\n"
            f"files:\n"
            f"  - url: {latest.file_name}\n"
            f"    sha512: {latest.checksum_sha512}\n"
            f"    size: {latest.file_size}\n"
            f"path: {latest.file_name}\n"
            f"sha512: {latest.checksum_sha512}\n"
            f"releaseDate: '{latest.created_at.isoformat()}'\n"
        )

        return HttpResponse(yml_content, content_type='text/yaml')


class VersionListView(APIView):
    """Admin: list all versions or create a new version record."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        platform = request.GET.get('platform', '')
        qs = ClientVersion.objects.all()
        if platform:
            qs = qs.filter(platform=platform)
        serializer = ClientVersionSerializer(qs[:50], many=True)
        return Response({'success': True, 'data': serializer.data})

    def post(self, request):
        serializer = ClientVersionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark previous versions as not latest
        platform = serializer.validated_data.get('platform', 'windows')
        if serializer.validated_data.get('is_latest'):
            ClientVersion.objects.filter(platform=platform, is_latest=True).update(is_latest=False)

        serializer.save()
        return Response(
            {'success': True, 'data': serializer.data},
            status=status.HTTP_201_CREATED,
        )


class VersionDetailView(APIView):
    """Admin: update or delete a version record."""

    permission_classes = [IsAdminUser]

    def put(self, request, pk):
        try:
            version = ClientVersion.objects.get(pk=pk)
        except ClientVersion.DoesNotExist:
            return Response(
                {'success': False, 'error': 'Not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ClientVersionSerializer(version, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if serializer.validated_data.get('is_latest'):
            ClientVersion.objects.filter(
                platform=version.platform, is_latest=True
            ).exclude(pk=pk).update(is_latest=False)

        serializer.save()
        return Response({'success': True, 'data': serializer.data})

    def delete(self, request, pk):
        try:
            version = ClientVersion.objects.get(pk=pk)
        except ClientVersion.DoesNotExist:
            return Response(
                {'success': False, 'error': 'Not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        version.delete()
        return Response({'success': True, 'message': 'Deleted'})
