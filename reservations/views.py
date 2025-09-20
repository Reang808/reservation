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
    """顧客向けカレンダー表示（認証不要）"""
    if tenant_slug:
        tenant = get_object_or_404(Tenant, slug=tenant_slug)
    else:
        # tenant_slugがない場合はエラーページ
        return render(request, 'reservations/access_denied.html', {
            'message': '店舗を指定してアクセスしてください。例: /tenant/店舗ID/'
        })
    
    # 週の計算
    week_offset = int(request.GET.get('week_offset', 0))
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [start_of_week + timedelta(days=i) for i in range(7)]
    
    # テナント設定による時間枠
    time_slots = get_tenant_time_slots(tenant)
    
    # 予約データ取得
    reservations = Reservation.objects.filter(tenant=tenant, date__in=week_days)
    res_dict = {f"{r.date}_{r.time_slot}": r for r in reservations}
    
    # カレンダーデータ構築
    calendar_rows = []
    for slot in time_slots:
        row = []
        for day in week_days:
            key = f"{day}_{slot}"
            reservation = res_dict.get(key)
            is_open = is_open_day(day, tenant)
            
            # 予約可能時間チェック
            now = datetime.now()
            slot_datetime = datetime.combine(day, slot)
            available = slot_datetime >= now + timedelta(hours=tenant.advance_hours)
            
            row.append({
                'day': day,
                'slot': slot,
                'reservation': reservation,
                'is_open_day': is_open,
                'available': available and is_open,
                'key': f"{day}_{slot.strftime('%H-%M')}"
            })
        calendar_rows.append(row)
    
    context = {
        'tenant': tenant,
        'tenant_slug': tenant_slug,
        'week_days': week_days,
        'time_slots': time_slots,
        'calendar_rows': calendar_rows,
        'week_offset': week_offset,
    }
    return render(request, 'reservations/calendar.html', context)

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
                customer_phone=customer_phone[:20],
                date=reserve_date,
                time_slot=reserve_time
            )
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
                return redirect('owner_reserve_list_by_tenant', tenant_slug=tenant.slug)
        return redirect('owner_reserve_calendar')
    
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
                    return redirect('owner_reserve_list_by_tenant', tenant_slug=tenant.slug)
                return redirect('owner_reserve_calendar')
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