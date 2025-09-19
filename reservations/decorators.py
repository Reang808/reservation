from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .models import Tenant
import logging

logger = logging.getLogger(__name__)

def role_required(roles):
    """指定された役割のユーザーのみアクセス可能"""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                logger.warning(f"Unauthenticated access attempt to {view_func.__name__}")
                return redirect('login')
            
            # ユーザーの役割を取得
            user_roles = []
            
            # スーパーユーザーは開発者として扱う
            if request.user.is_superuser:
                user_roles.append('developer')
            
            # roleアトリビュートが存在する場合のチェック
            if hasattr(request.user, 'role'):
                if request.user.role == 'developer':
                    user_roles.append('developer')
                elif request.user.role == 'owner':
                    user_roles.extend(['owner', 'customer'])  # オーナーは顧客機能も使用可能
                elif request.user.role == 'customer':
                    user_roles.append('customer')
            else:
                # roleアトリビュートがない場合のフォールバック
                if request.user.is_staff:
                    user_roles.append('developer')
                else:
                    user_roles.append('customer')
            
            # 権限チェック
            if not any(role in roles for role in user_roles):
                logger.warning(f"Access denied for user {request.user.id} with roles {user_roles} to {view_func.__name__} requiring {roles}")
                return render(request, 'reservations/access_denied.html', {
                    'required_roles': roles,
                    'user_role': getattr(request.user, 'role', 'unknown'),
                    'message': f'この機能にアクセスするには {", ".join(roles)} の権限が必要です。'
                })
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def tenant_owner_required(view_func):
    """テナントのオーナーまたは開発者のみアクセス可能"""
    @wraps(view_func)
    @login_required
    def wrapper(request, tenant_slug, *args, **kwargs):
        if not request.user.is_authenticated:
            logger.warning(f"Unauthenticated access attempt to tenant {tenant_slug}")
            return redirect('login')
        
        # 開発者権限チェック（スーパーユーザーまたはrole='developer'）
        is_developer = request.user.is_superuser or (
            hasattr(request.user, 'role') and request.user.role == 'developer'
        )
        
        if is_developer:
            # 開発者は全てのテナントにアクセス可能
            logger.info(f"Developer access to tenant {tenant_slug} by user {request.user.id}")
            return view_func(request, tenant_slug, *args, **kwargs)
        
        # テナントの存在確認
        try:
            tenant = get_object_or_404(Tenant, slug=tenant_slug)
        except Exception as e:
            logger.error(f"Tenant not found: {tenant_slug}, error: {str(e)}")
            return render(request, 'reservations/access_denied.html', {
                'message': 'テナントが見つかりません。'
            })
        
        # オーナー権限チェック
        is_owner = (
            hasattr(request.user, 'role') and 
            request.user.role == 'owner' and 
            tenant.owner == request.user
        )
        
        if not is_owner:
            logger.warning(f"Access denied to tenant {tenant_slug} for user {request.user.id}")
            return render(request, 'reservations/owner_no_tenant.html', {
                'message': 'このテナントの管理権限がありません。'
            })
        
        logger.info(f"Owner access to tenant {tenant_slug} by user {request.user.id}")
        return view_func(request, tenant_slug, *args, **kwargs)
    return wrapper

def developer_required(view_func):
    """開発者のみアクセス可能"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        is_developer = request.user.is_superuser or (
            hasattr(request.user, 'role') and request.user.role == 'developer'
        )
        
        if not is_developer:
            logger.warning(f"Non-developer access attempt to {view_func.__name__} by user {request.user.id}")
            raise PermissionDenied("開発者権限が必要です。")
        
        return view_func(request, *args, **kwargs)
    return wrapper

def safe_tenant_access(view_func):
    """安全なテナントアクセス（存在チェック付き）"""
    @wraps(view_func)
    def wrapper(request, tenant_slug, *args, **kwargs):
        try:
            tenant = get_object_or_404(Tenant, slug=tenant_slug)
            # テナントオブジェクトをrequestに追加
            request.tenant = tenant
            return view_func(request, tenant_slug, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error accessing tenant {tenant_slug}: {str(e)}")
            return render(request, 'reservations/access_denied.html', {
                'message': 'テナントにアクセスできません。'
            })
    return wrapper
