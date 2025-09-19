from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from datetime import time

class CustomUser(AbstractUser):
    USER_ROLES = [
        ('customer', '顧客'),
        ('owner', '事業者'),
        ('developer', '開発者'),
    ]
    
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=USER_ROLES, default='customer', verbose_name='ユーザー種別')
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
    
    def is_developer(self):
        return self.role == 'developer' or self.is_superuser
    
    def is_owner(self):
        return self.role == 'owner' or self.is_developer()
    
    def is_customer(self):
        return self.role == 'customer'

class Tenant(models.Model):
    name = models.CharField(max_length=100, verbose_name='店舗名')
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True, verbose_name='URL識別子')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenants', verbose_name='オーナー')
    
    # 予約カレンダー設定（バリデーション追加）
    start_time = models.TimeField(default=time(8, 0), help_text='営業開始時間')
    end_time = models.TimeField(default=time(20, 0), help_text='営業終了時間')
    slot_duration = models.IntegerField(
        default=60, 
        validators=[MinValueValidator(15), MaxValueValidator(240)],
        help_text='予約枠の長さ（分）15-240分'
    )
    advance_hours = models.IntegerField(
        default=4, 
        validators=[MinValueValidator(0), MaxValueValidator(168)],
        help_text='予約可能になる時間（現在時刻から何時間後）0-168時間'
    )
    
    # 曜日別営業設定
    monday_open = models.BooleanField(default=True, verbose_name='月曜日営業')
    tuesday_open = models.BooleanField(default=True, verbose_name='火曜日営業')
    wednesday_open = models.BooleanField(default=True, verbose_name='水曜日営業')
    thursday_open = models.BooleanField(default=True, verbose_name='木曜日営業')
    friday_open = models.BooleanField(default=True, verbose_name='金曜日営業')
    saturday_open = models.BooleanField(default=True, verbose_name='土曜日営業')
    sunday_open = models.BooleanField(default=True, verbose_name='日曜日営業')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')
    
    class Meta:
        verbose_name = 'テナント'
        verbose_name_plural = 'テナント'
        ordering = ['name']
    
    def clean(self):
        """モデルレベルでのバリデーション"""
        super().clean()
        if self.start_time >= self.end_time:
            raise ValidationError('営業開始時間は営業終了時間より前である必要があります。')
        
        # 少なくとも1日は営業している必要がある
        open_days = [
            self.monday_open, self.tuesday_open, self.wednesday_open,
            self.thursday_open, self.friday_open, self.saturday_open, self.sunday_open
        ]
        if not any(open_days):
            raise ValidationError('少なくとも1日は営業日を設定してください。')
    
    def __str__(self):
        return self.name
    
    def get_open_days(self):
        """営業日のリストを返す"""
        return [
            (0, self.monday_open),    # 月曜日
            (1, self.tuesday_open),   # 火曜日
            (2, self.wednesday_open), # 水曜日
            (3, self.thursday_open),  # 木曜日
            (4, self.friday_open),    # 金曜日
            (5, self.saturday_open),  # 土曜日
            (6, self.sunday_open),    # 日曜日
        ]
    
    def save(self, *args, **kwargs):
        # フルクリーンバリデーションを実行
        self.full_clean()
        
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Tenant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

class Menu(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='menus', verbose_name='テナント')
    name = models.CharField(max_length=100, verbose_name='メニュー名')
    description = models.TextField(blank=True, verbose_name='説明')
    price = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='価格'
    )
    is_active = models.BooleanField(default=True, verbose_name='有効')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    
    class Meta:
        verbose_name = 'メニュー'
        verbose_name_plural = 'メニュー'
        ordering = ['name']
        unique_together = ['tenant', 'name']  # 同一テナント内でのメニュー名重複防止
    
    def __str__(self):
        return f"{self.tenant.name} - {self.name}"

class Reservation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='reservations', verbose_name='テナント')
    menu = models.ForeignKey(Menu, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservations', verbose_name='メニュー')
    customer_name = models.CharField(max_length=100, verbose_name='顧客名')
    date = models.DateField(verbose_name='予約日')
    time_slot = models.TimeField(verbose_name='予約時間')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='予約作成日時')
    
    class Meta:
        verbose_name = '予約'
        verbose_name_plural = '予約'
        ordering = ['-date', '-time_slot']
        unique_together = ['tenant', 'date', 'time_slot']  # 重複予約防止
        indexes = [
            models.Index(fields=['tenant', 'date']),
            models.Index(fields=['date', 'time_slot']),
        ]
    
    def clean(self):
        """予約のバリデーション"""
        super().clean()
        from datetime import datetime, timedelta
        
        # 過去の日付への予約を防ぐ
        today = datetime.now().date()
        if self.date < today:
            raise ValidationError('過去の日付には予約できません。')
        
        # メニューとテナントの整合性チェック
        if self.menu and self.menu.tenant != self.tenant:
            raise ValidationError('選択されたメニューはこのテナントのものではありません。')
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.tenant.name} {self.date} {self.time_slot} {self.customer_name}"
