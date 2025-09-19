from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Tenant, Menu, Reservation

class MenuInline(admin.TabularInline):
	model = Menu
	extra = 1

class ReservationInline(admin.TabularInline):
	model = Reservation
	extra = 0
	readonly_fields = ('menu', 'customer_name', 'date', 'time_slot', 'created_at')
	can_delete = True

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
	list_display = ('name', 'owner', 'start_time', 'end_time', 'slot_duration')
	search_fields = ('name', 'owner__username')
	inlines = [MenuInline, ReservationInline]
	
	fieldsets = (
		('基本情報', {
			'fields': ('name', 'slug', 'owner')
		}),
		('予約設定', {
			'fields': ('start_time', 'end_time', 'slot_duration', 'advance_hours'),
			'description': '予約カレンダーの基本設定'
		}),
		('営業日設定', {
			'fields': (
				('monday_open', 'tuesday_open', 'wednesday_open'),
				('thursday_open', 'friday_open', 'saturday_open'),
				'sunday_open'
			),
			'description': '曜日別の営業日設定'
		}),
	)

@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
	list_display = ('id', 'tenant', 'name', 'price')
	search_fields = ('name', 'tenant__name')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ('id', 'tenant', 'menu', 'customer_name', 'date', 'time_slot', 'created_at')
	search_fields = ('customer_name', 'tenant__name', 'menu__name')
	list_filter = ('tenant', 'date')

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
	list_display = ('username', 'email', 'role', 'first_name', 'last_name', 'is_staff')
	search_fields = ('username', 'email', 'first_name', 'last_name')
	list_filter = ('role', 'is_staff', 'is_superuser', 'is_active', 'date_joined')
	
	fieldsets = UserAdmin.fieldsets + (
		('追加情報', {'fields': ('role',)}),
	)
	
	add_fieldsets = UserAdmin.add_fieldsets + (
		('追加情報', {'fields': ('role',)}),
	)
	
	def save_model(self, request, obj, form, change):
		# スーパーユーザーは自動的に開発者権限を付与
		if obj.is_superuser and obj.role == 'customer':
			obj.role = 'developer'
		super().save_model(request, obj, form, change)
