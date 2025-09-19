from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import views_owner
from . import views_menu_owner

urlpatterns = [
    # 認証関連
    path('', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # 顧客向け（認証不要）
    path('tenant/<slug:tenant_slug>/', views.calendar_view, name='calendar_by_tenant'),
    path('tenant/<slug:tenant_slug>/reserve/', views.reserve_slot, name='reserve_slot_by_tenant'),
    
    # 開発者専用
    path('/developer/', views.developer_dashboard, name='developer_dashboard'),
    path('/developer/tenants/', views_owner.developer_tenant_list, name='developer_tenant_list'),

    # 事業者専用 - 基本機能（後方互換性のため残す）
    path('owner/reserve/', views_owner.owner_reserve_list, name='owner_reserve_list'),
    path('owner/reserve/calendar/', views_owner.owner_reserve_calendar, name='owner_reserve_calendar'),
    path('owner/reserve/delete/<int:reserve_id>/', views_owner.owner_reserve_delete, name='owner_reserve_delete'),
    path('owner/menu/', views_menu_owner.owner_menu_list, name='owner_menu_list'),
    path('owner/menu/add/', views_menu_owner.owner_menu_add, name='owner_menu_add'),
    path('owner/menu/<int:menu_id>/edit/', views_menu_owner.owner_menu_edit, name='owner_menu_edit'),
    path('owner/menu/<int:menu_id>/delete/', views_menu_owner.owner_menu_delete, name='owner_menu_delete'),
    
    # 事業者専用 - テナント指定（推奨）
    path('owner/tenant/<slug:tenant_slug>/reserve/', views_owner.owner_reserve_list_by_tenant, name='owner_reserve_list_by_tenant'),
    path('owner/tenant/<slug:tenant_slug>/menu/', views_menu_owner.owner_menu_list_by_tenant, name='owner_menu_list_by_tenant'),
    
    # 非推奨/削除予定（セキュリティ上問題のあるパターン）
    # path('calendar/', views.calendar_view, name='calendar'),  # tenant_slug不要のため削除
    # path('reserve/', views.reserve_slot, name='reserve_slot'),  # tenant_slug不要のため削除
]

# 開発環境でのデバッグ用（本番環境では削除すること）
# if settings.DEBUG:
#     urlpatterns += [
#         path('debug/users/', views.debug_user_list, name='debug_user_list'),
#         path('debug/reservations/', views.debug_reservation_list, name='debug_reservation_list'),
#     ]