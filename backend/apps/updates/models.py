from django.db import models


class ClientVersion(models.Model):
    """客户端版本记录"""

    PLATFORM_CHOICES = [
        ('windows', 'Windows'),
        ('mac', 'macOS'),
        ('linux', 'Linux'),
    ]

    version = models.CharField('版本号', max_length=20, db_index=True)
    platform = models.CharField('平台', max_length=20, choices=PLATFORM_CHOICES, default='windows')
    file_name = models.CharField('安装包文件名', max_length=255)
    file_size = models.BigIntegerField('文件大小(字节)', default=0)
    download_url = models.CharField('下载路径', max_length=500)
    checksum_sha512 = models.CharField('SHA512校验值', max_length=128, blank=True, default='')
    release_notes = models.TextField('更新日志', blank=True, default='')
    is_latest = models.BooleanField('是否最新版', default=False, db_index=True)
    created_at = models.DateTimeField('发布时间', auto_now_add=True)
    download_count = models.IntegerField('下载次数', default=0)

    class Meta:
        verbose_name = '客户端版本'
        verbose_name_plural = '客户端版本'
        ordering = ['-created_at']
        unique_together = [('version', 'platform')]

    def __str__(self):
        return f'v{self.version} ({self.platform})'
