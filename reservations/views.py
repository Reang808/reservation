from django.conf import settings
from twilio.rest import Client
# TwilioでSMS送信
def send_sms(to_number, message):
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER
    client = Client(account_sid, auth_token)
    try:
        client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
    except Exception as e:
        print(f"SMS送信エラー: {e}")
from django.contrib.auth import authenticate, login
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import datetime, date, timedelta
from .models import Tenant, Menu, Reservation
from .decorators import role_required

# CustomUserのimport（存在確認）
try:
    from .models import CustomUser
except ImportError:
    from django.contrib.auth.models import User as CustomUser

def get_tenant_time_slots(tenant):
    """テナント設定に基づく時間枠生成"""
    slots = []
    current = datetime.combine(date.today(), tenant.start_time)
    end = datetime.combine(date.today(), tenant.end_time)
    
    while current.time() < end.time():
        slots.append(current.time())
        current += timedelta(minutes=tenant.slot_duration)
    
    return slots

def is_open_day(day, tenant):
    """営業日判定"""
    weekday = day.weekday()
    days = [tenant.monday_open, tenant.tuesday_open, tenant.wednesday_open,
            tenant.thursday_open, tenant.friday_open, tenant.saturday_open, tenant.sunday_open]
    return days[weekday]

def calendar_view(request, tenant_slug=None):
    """顧客向けカレンダー表示（新しい月表示カレンダー）"""
    if tenant_slug:
        tenant = get_object_or_404(Tenant, slug=tenant_slug)
    else:
        # tenant_slugがない場合はエラーページ
        return render(request, 'reservations/access_denied.html', {
            'message': '店舗を指定してアクセスしてください。例: /tenant/店舗ID/'
        })
    
    # 新しいカレンダー用のシンプルなコンテキスト
    return render(request, 'reservations/calendar.html', {
        'tenant': tenant
    })

# CSRFデコレータを削除し、適切なセキュリティを実装
def reserve_slot(request, tenant_slug=None):
    """予約処理（セキュリティ強化版）"""
    if request.method != 'POST':
        if tenant_slug:
            return redirect('calendar_by_tenant', tenant_slug=tenant_slug)
        return redirect('login')
    
    if tenant_slug:
        tenant = get_object_or_404(Tenant, slug=tenant_slug)
    else:
        return redirect('login')
    
    # 入力値の検証を強化
    date_str = request.POST.get('date', '').strip()
    time_str = request.POST.get('time_slot', '').strip()
    menu_id = request.POST.get('menu_id', '').strip()
    customer_name = request.POST.get('customer_name', '').strip()
    customer_email = request.POST.get('customer_email', '').strip()
    customer_phone = request.POST.get('customer_phone', '').strip()
    
    # バリデーション
    if not all([date_str, time_str, customer_name, customer_phone]):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse('必須項目が不足しています', status=400)
        return redirect('calendar_by_tenant', tenant_slug=tenant_slug)
    
    try:
        reserve_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        reserve_time = datetime.strptime(time_str, '%H:%M').time()
        
        # 営業日チェック
        if not is_open_day(reserve_date, tenant):
            raise ValueError("営業日ではありません")
        
        # 予約可能時間チェック
        now = datetime.now()
        slot_datetime = datetime.combine(reserve_date, reserve_time)
        if slot_datetime < now + timedelta(hours=tenant.advance_hours):
            raise ValueError("予約可能時間外です")
        
        # 重複チェック
        if not Reservation.objects.filter(tenant=tenant, date=reserve_date, time_slot=reserve_time).exists():
            menu = Menu.objects.filter(id=menu_id, tenant=tenant).first() if menu_id else None
            reservation = Reservation.objects.create(
                tenant=tenant,
                menu=menu,
                customer_name=customer_name[:100],  # 長さ制限
                customer_email=customer_email,
                customer_phone=customer_phone[:20],
                date=reserve_date,
                time_slot=reserve_time
            )
            
            # SMS通知（ブロック予約でない場合のみ）
            if customer_name != 'BLOCKED':
                # 顧客へSMS通知
                sms_msg = f"{tenant.name}のご予約が完了しました。\n日時: {reserve_date} {reserve_time.strftime('%H:%M')}\nお名前: {customer_name}"
                send_sms(customer_phone, sms_msg)

                # 事業者へSMS通知（オーナーの電話番号があれば）
                owner_phone = getattr(tenant.owner, 'phone', None)
                if owner_phone:
                    owner_msg = f"新しい予約が入りました。\n日時: {reserve_date} {reserve_time.strftime('%H:%M')}\n顧客: {customer_name}"
                    send_sms(owner_phone, owner_msg)
        else:
            raise ValueError("この時間は既に予約済みです")
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success'})
            
    except ValueError as e:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse(str(e), status=400)
    except Exception as e:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse('予約処理でエラーが発生しました', status=500)
    
    return redirect('calendar_by_tenant', tenant_slug=tenant_slug)

@role_required(['developer'])
def developer_dashboard(request):
    """開発者用ダッシュボード"""
    tenants = Tenant.objects.all().order_by('name')
    try:
        users = CustomUser.objects.all().order_by('-date_joined')[:10]
    except Exception:
        users = []
    total_reservations = Reservation.objects.count()
    
    context = {
        'tenants': tenants,
        'users': users,
        'total_reservations': total_reservations,
    }
    return render(request, 'reservations/developer_dashboard.html', context)

def login_view(request):
    """ログイン画面"""
    if request.user.is_authenticated:
        # 既にログインしている場合は事業者画面にリダイレクト
        if hasattr(request.user, 'role') and request.user.role == 'owner':
            tenant = Tenant.objects.filter(owner=request.user).first()
            if tenant:
                return redirect('owner_calendar_view', tenant_slug=tenant.slug)
        tenant = Tenant.objects.filter(owner=request.user).first()
        if tenant:
            return redirect('owner_calendar_view', tenant_slug=tenant.slug)
        return redirect('developer_tenant_list')
    
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            # ログイン成功後のリダイレクト
            if user.is_superuser or (hasattr(user, 'role') and user.role in ['owner', 'developer']):
                if hasattr(user, 'role') and user.role == 'developer':
                    return redirect('developer_tenant_list')
                tenant = Tenant.objects.filter(owner=user).first()
                if tenant:
                    return redirect('owner_calendar_view', tenant_slug=tenant.slug)
                tenant = Tenant.objects.filter(owner=user).first()
                if tenant:
                    return redirect('owner_calendar_view', tenant_slug=tenant.slug)
                return redirect('developer_tenant_list')
            else:
                error = "事業者アカウントでログインしてください。"
        else:
            error = "ユーザー名またはパスワードが正しくありません。"
    
    # 顧客向けのテナント一覧を取得（全件表示）
    tenants = Tenant.objects.all().order_by('name')
    
    return render(request, 'reservations/login.html', {
        'error': error,
        'tenants': tenants
    })

# ===========================================
# API エンドポイント（学習用）
# ===========================================

def api_tenant_info(request, tenant_slug):
    """
    最初のAPI: テナント情報を取得
    使い方: /tenant/reang/api/info/
    """
    # テナントを取得
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # テナント情報をJSON形式で返す
    tenant_data = {
        'name': tenant.name,
        'slug': tenant.slug,
        'start_time': tenant.start_time.strftime('%H:%M'),
        'end_time': tenant.end_time.strftime('%H:%M'),
        'slot_duration': tenant.slot_duration,
        'business_days': {
            'monday': tenant.monday_open,
            'tuesday': tenant.tuesday_open,
            'wednesday': tenant.wednesday_open,
            'thursday': tenant.thursday_open,
            'friday': tenant.friday_open,
            'saturday': tenant.saturday_open,
            'sunday': tenant.sunday_open,
        }
    }
    
    return JsonResponse(tenant_data)

def api_get_slots(request, tenant_slug):
    """
    ステップ2のAPI: 指定日の時間スロット取得
    使い方: /tenant/test/api/slots/?date=2025-10-01
    """
    # URLパラメータから日付を取得
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': '日付が指定されていません'}, status=400)
    
    try:
        # 日付文字列をDateオブジェクトに変換
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '日付の形式が正しくありません'}, status=400)
    
    # テナント情報を取得
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # 営業日チェック
    if not is_open_day(target_date, tenant):
        return JsonResponse({
            'slots': [],
            'message': 'この日は営業日ではありません'
        })
    
    # 時間スロットを生成
    slots = []
    current_time = datetime.combine(target_date, tenant.start_time)
    end_time = datetime.combine(target_date, tenant.end_time)
    
    while current_time < end_time:
        time_str = current_time.strftime('%H:%M')
        
        # 既存の予約をチェック
        is_reserved = Reservation.objects.filter(
            tenant=tenant,
            date=target_date,
            time_slot=current_time.time()
        ).exists()
        
        # 予約可能時間チェック（現在時刻から指定時間後以降）
        now = timezone.now()
        slot_datetime = timezone.make_aware(current_time)
        is_available = slot_datetime >= now + timedelta(hours=tenant.advance_hours)
        
        slots.append({
            'time': time_str,
            'is_available': is_available and not is_reserved,
            'is_reserved': is_reserved
        })
        
        # 次の時間スロットに進む
        current_time += timedelta(minutes=tenant.slot_duration)
    
    return JsonResponse({
        'slots': slots,
        'date': date_str,
        'tenant_name': tenant.name
    })