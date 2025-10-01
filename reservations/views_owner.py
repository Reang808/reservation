from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta, time, date
from .models import Menu, Reservation, Tenant
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .decorators import role_required, tenant_owner_required
from .views import is_open_day
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
import logging

logger = logging.getLogger(__name__)

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

@role_required(['developer'])
def developer_tenant_list(request):
    """開発者用テナント一覧"""
    tenants = Tenant.objects.all().order_by('name')
    context = {
        'tenants': tenants,
    }
    return render(request, 'reservations/developer_tenant_list.html', context)

@tenant_owner_required
def owner_reserve_list_by_tenant(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # 開発者またはテナントオーナーのみアクセス可能（decoratorで制御済み）
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
            
            row.append({
                'day': day,
                'slot': slot,
                'reservation': reservation,
                'is_open_day': is_open,
                'key': f"{day}_{slot.strftime('%H-%M')}"
            })
        calendar_rows.append(row)
    
    menus = Menu.objects.filter(tenant=tenant, is_active=True)
    
    # 予約追加処理（バリデーション強化）
    if request.method == 'POST' and request.POST.get('action') == 'add':
        date_str = request.POST.get('date', '').strip()
        time_str = request.POST.get('time_slot', '').strip()
        menu_id = request.POST.get('menu_id', '').strip()
        customer_name = request.POST.get('customer_name', '').strip()
        customer_email = request.POST.get('customer_email', '').strip()
        customer_phone = request.POST.get('customer_phone', '').strip()
        
        try:
            # 入力値検証
            if not all([date_str, time_str, customer_name, customer_phone]):
                raise ValidationError('必須項目が不足しています。')
            
            if len(customer_name) > 100:
                raise ValidationError('顧客名は100文字以内で入力してください。')
            
            reserve_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            reserve_time = datetime.strptime(time_str, '%H:%M').time()
            
            # 営業日チェック
            if not is_open_day(reserve_date, tenant):
                raise ValidationError('営業日ではありません。')
            
            # 重複チェック
            if Reservation.objects.filter(tenant=tenant, date=reserve_date, time_slot=reserve_time).exists():
                raise ValidationError('この時間枠は既に予約済みです。')
            
            menu = None
            if menu_id:
                menu = Menu.objects.filter(id=menu_id, tenant=tenant, is_active=True).first()
                if not menu:
                    raise ValidationError('選択されたメニューが見つかりません。')
            
            Reservation.objects.create(
                tenant=tenant,
                menu=menu,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                date=reserve_date,
                time_slot=reserve_time
            )
            
            messages.success(request, '予約を追加し、確認メールを送信しました。')
            logger.info(f"Reservation created by user {request.user.id} for tenant {tenant.slug}")
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
                
        except ValidationError as e:
            messages.error(request, str(e))
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)})
        except Exception as e:
            logger.error(f"Error creating reservation: {str(e)}")
            messages.error(request, '予約の作成に失敗しました。')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': '予約の作成に失敗しました。'})
        
        return redirect('owner_calendar_view', tenant_slug=tenant.slug)
    
    # 予約削除処理（権限チェック強化）
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        reserve_id = request.POST.get('reserve_id')
        try:
            reservation = get_object_or_404(Reservation, id=reserve_id, tenant=tenant)
            reservation.delete()
            messages.success(request, '予約を削除しました。')
            logger.info(f"Reservation {reserve_id} deleted by user {request.user.id}")
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
        except Exception as e:
            logger.error(f"Error deleting reservation: {str(e)}")
            messages.error(request, '予約の削除に失敗しました。')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': '予約の削除に失敗しました。'})
        
        return redirect('owner_calendar_view', tenant_slug=tenant.slug)
    
    # メニュー管理処理（バリデーション強化）
    if request.method == 'POST' and request.POST.get('action') == 'menu':
        menu_action = request.POST.get('menu_action')
        
        try:
            if menu_action == 'add':
                menu_name = request.POST.get('menu_name', '').strip()
                if not menu_name:
                    raise ValidationError('メニュー名は必須です。')
                if len(menu_name) > 100:
                    raise ValidationError('メニュー名は100文字以内で入力してください。')
                
                # 同名メニューチェック
                if Menu.objects.filter(tenant=tenant, name=menu_name).exists():
                    raise ValidationError('同じ名前のメニューが既に存在します。')
                
                price = request.POST.get('menu_price', '').strip()
                if price:
                    try:
                        price = float(price)
                        if price < 0:
                            raise ValidationError('価格は0以上で入力してください。')
                    except ValueError:
                        raise ValidationError('価格は数値で入力してください。')
                else:
                    price = None
                
                Menu.objects.create(
                    tenant=tenant,
                    name=menu_name,
                    description=request.POST.get('menu_description', ''),
                    price=price
                )
                messages.success(request, 'メニューを追加しました。')
                
            elif menu_action == 'edit':
                menu_id = request.POST.get('menu_id')
                menu = get_object_or_404(Menu, id=menu_id, tenant=tenant)
                
                menu_name = request.POST.get('menu_name', '').strip()
                if not menu_name:
                    raise ValidationError('メニュー名は必須です。')
                
                # 同名メニューチェック（自分以外）
                if Menu.objects.filter(tenant=tenant, name=menu_name).exclude(id=menu.id).exists():
                    raise ValidationError('同じ名前のメニューが既に存在します。')
                
                menu.name = menu_name
                menu.description = request.POST.get('menu_description', '')
                
                price = request.POST.get('menu_price', '').strip()
                if price:
                    try:
                        menu.price = float(price)
                        if menu.price < 0:
                            raise ValidationError('価格は0以上で入力してください。')
                    except ValueError:
                        raise ValidationError('価格は数値で入力してください。')
                else:
                    menu.price = None
                
                menu.save()
                messages.success(request, 'メニューを更新しました。')
                
            elif menu_action == 'delete':
                menu_id = request.POST.get('menu_id')
                menu = get_object_or_404(Menu, id=menu_id, tenant=tenant)
                menu.delete()
                messages.success(request, 'メニューを削除しました。')
                
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f"Error in menu management: {str(e)}")
            messages.error(request, 'メニュー操作に失敗しました。')
        
        return redirect('owner_calendar_view', tenant_slug=tenant.slug)
    
    # 全予約一覧（最近の予約順）
    all_reservations = Reservation.objects.filter(tenant=tenant).order_by('-date', '-time_slot')[:50]
    
    context = {
        'tenant': tenant,
        'week_days': week_days,
        'time_slots': time_slots,
        'calendar_rows': calendar_rows,
        'menus': menus,
        'reservations': all_reservations,
        'week_offset': week_offset,
    }
    return render(request, 'reservations/owner_reserve_list.html', context)

@role_required(['owner', 'developer'])
def owner_reserve_calendar(request):
    # 開発者用のテナント選択
    if hasattr(request.user, 'role') and request.user.role == 'developer':
        tenant_id = request.GET.get('tenant_id')
        if tenant_id:
            tenant = Tenant.objects.filter(id=tenant_id).first()
        else:
            return redirect('developer_tenant_list')
    else:
        tenant = Tenant.objects.filter(owner=request.user).first()
    
    if not tenant:
        return render(request, 'reservations/owner_no_tenant.html')
    
    # カレンダー表示範囲
    week_offset = int(request.GET.get('week_offset', 0))
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [start_of_week + timedelta(days=i) for i in range(7)]
    time_slots = [time(hour=h) for h in range(8, 21, 2)]
    reservations = Reservation.objects.filter(tenant=tenant, date__in=week_days)
    res_dict = {f"{r.date.strftime('%Y-%m-%d')}_{r.time_slot.strftime('%H:%M')}": r for r in reservations}
    calendar_rows = []
    for slot in time_slots:
        row = []
        for day in week_days:
            key = f"{day.strftime('%Y-%m-%d')}_{slot.strftime('%H:%M')}"
            reservation = res_dict.get(key)
            row.append({'slot': slot, 'reservation': reservation, 'day': day})
        calendar_rows.append(row)
    menus = Menu.objects.filter(tenant=tenant)
    # 予約追加
    if request.method == 'POST' and 'customer_name' in request.POST:
        date = request.POST.get('date')
        time_slot = request.POST.get('time_slot')
        menu_id = request.POST.get('menu_id')
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email', '')
        customer_phone = request.POST.get('customer_phone', '')
        
        try:
            slot_time = datetime.strptime(time_slot, '%H:%M').time()
            exists = Reservation.objects.filter(tenant=tenant, date=date, time_slot=slot_time).exists()
            
            if not exists:
                menu = Menu.objects.filter(id=menu_id, tenant=tenant).first() if menu_id else None
                
                Reservation.objects.create(
                    tenant=tenant,
                    menu=menu,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    date=date,
                    time_slot=slot_time
                )
                messages.success(request, '予約を追加しました。')
            else:
                messages.error(request, 'この時間枠は既に予約済みです。')
                
        except Exception as e:
            logger.error(f"Error creating reservation: {str(e)}")
            messages.error(request, '予約の作成に失敗しました。')
            
        return redirect('owner_reserve_calendar')
    
    context = {
        'tenant': tenant,
        'week_days': week_days,
        'time_slots': time_slots,
        'calendar_rows': calendar_rows,
        'menus': menus,
    }
    return render(request, 'reservations/owner_reserve_calendar.html', context)

@role_required(['owner', 'developer'])
def owner_reserve_delete(request, reserve_id):
    # 開発者またはオーナーの権限チェック
    if hasattr(request.user, 'role') and request.user.role == 'developer':
        reservation = get_object_or_404(Reservation, id=reserve_id)
    else:
        # オーナーは自分のテナントの予約のみ削除可能
        user_tenants = Tenant.objects.filter(owner=request.user)
        reservation = get_object_or_404(Reservation, id=reserve_id, tenant__in=user_tenants)
    
    if request.method == 'POST':
        try:
            reservation.delete()
            messages.success(request, '予約を削除しました。')
            logger.info(f"Reservation {reserve_id} deleted by user {request.user.id}")
        except Exception as e:
            logger.error(f"Error deleting reservation: {str(e)}")
            messages.error(request, '予約の削除に失敗しました。')
    
    return redirect('owner_reserve_calendar')

@role_required(['owner', 'developer'])
def owner_reserve_list(request):
    # 開発者用のテナント選択
    if hasattr(request.user, 'role') and request.user.role == 'developer':
        tenant_id = request.GET.get('tenant_id')
        if tenant_id:
            tenant = Tenant.objects.filter(id=tenant_id).first()
        else:
            return redirect('developer_tenant_list')
    else:
        tenant = Tenant.objects.filter(owner=request.user).first()
    
    if not tenant:
        return render(request, 'reservations/owner_no_tenant.html')
    week_offset = int(request.GET.get('week_offset', 0))
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [start_of_week + timedelta(days=i) for i in range(7)]
    time_slots = [time(hour=h) for h in range(8, 21, 2)]
    reservations = Reservation.objects.filter(tenant=tenant, date__in=week_days)
    res_dict = {f"{r.date.strftime('%Y-%m-%d')}_{r.time_slot.strftime('%H:%M')}": r for r in reservations}
    calendar_rows = []
    for slot in time_slots:
        row = []
        for day in week_days:
            key = f"{day.strftime('%Y-%m-%d')}_{slot.strftime('%H:%M')}"
            reservation = res_dict.get(key)
            row.append({'slot': slot, 'reservation': reservation, 'day': day})
        calendar_rows.append(row)
    menus = Menu.objects.filter(tenant=tenant)
    # 予約追加
    if request.method == 'POST' and request.POST.get('action') == 'add':
        date = request.POST.get('date')
        time_slot = request.POST.get('time_slot')
        menu_id = request.POST.get('menu_id')
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email', '')
        customer_phone = request.POST.get('customer_phone', '')
        
        try:
            slot_time = datetime.strptime(time_slot, '%H:%M').time()
            exists = Reservation.objects.filter(tenant=tenant, date=date, time_slot=slot_time).exists()
            
            if not exists:
                menu = Menu.objects.filter(id=menu_id, tenant=tenant).first() if menu_id else None
                
                Reservation.objects.create(
                    tenant=tenant,
                    menu=menu,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    date=date,
                    time_slot=slot_time
                )
                messages.success(request, '予約を追加しました。')
            else:
                messages.error(request, 'この時間枠は既に予約済みです。')
                
        except Exception as e:
            logger.error(f"Error creating reservation: {str(e)}")
            messages.error(request, '予約の作成に失敗しました。')
            
        return redirect('owner_reserve_list')
    
    # 予約削除
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        reserve_id = request.POST.get('reserve_id')
        reservation = Reservation.objects.filter(id=reserve_id, tenant=tenant).first()
        if reservation:
            reservation.delete()
        return redirect('owner_reserve_list')
    # 予約一覧（全期間）
    all_reservations = Reservation.objects.filter(tenant=tenant).order_by('-date', '-time_slot')
    context = {
        'tenant': tenant,
        'week_days': week_days,
        'time_slots': time_slots,
        'calendar_rows': calendar_rows,
        'menus': menus,
        'reservations': all_reservations,
    }
    return render(request, 'reservations/owner_reserve_list.html', context)

@tenant_owner_required
def owner_email_settings(request, tenant_slug):
    """メール設定画面"""
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    if request.method == 'POST':
        try:
            # フォームデータの取得と保存
            tenant.notification_email = request.POST.get('notification_email', '').strip()
            tenant.customer_email_subject = request.POST.get('customer_email_subject', '').strip()
            tenant.customer_email_message = request.POST.get('customer_email_message', '').strip()
            tenant.owner_email_subject = request.POST.get('owner_email_subject', '').strip()
            tenant.owner_email_message = request.POST.get('owner_email_message', '').strip()
            
            # バリデーション
            if not tenant.customer_email_subject:
                raise ValidationError('予約確認メール件名は必須です。')
            if not tenant.customer_email_message:
                raise ValidationError('予約確認メール本文は必須です。')
            if not tenant.owner_email_subject:
                raise ValidationError('予約通知メール件名は必須です。')
            if not tenant.owner_email_message:
                raise ValidationError('予約通知メール本文は必須です。')
            
            tenant.save()
            messages.success(request, 'メール設定を保存しました。')
            
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f"Error saving email settings: {str(e)}")
            messages.error(request, 'メール設定の保存に失敗しました。')
        
        return redirect('owner_email_settings', tenant_slug=tenant.slug)
    
    context = {
        'tenant': tenant,
    }
    return render(request, 'reservations/owner_email_settings.html', context)

@role_required(['owner'])
@tenant_owner_required
def owner_calendar_view(request, tenant_slug):
    """オーナー向けカレンダー表示"""
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    return render(request, 'reservations/owner_calendar.html', {
        'tenant': tenant
    })

@role_required(['owner'])
@tenant_owner_required
def api_owner_slots(request, tenant_slug):
    """オーナー向け時間スロット取得API（予約情報付き）"""
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': '日付が指定されていません'}, status=400)
    
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': '日付の形式が正しくありません'}, status=400)
    
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
        reservation = Reservation.objects.filter(
            tenant=tenant,
            date=target_date,
            time_slot=current_time.time()
        ).first()
        
        slots.append({
            'time': time_str,
            'is_available': reservation is None,
            'is_reserved': reservation is not None,
            'reservation_id': reservation.id if reservation else None,
            'customer_name': reservation.customer_name if reservation else None
        })
        
        current_time += timedelta(minutes=tenant.slot_duration)
    
    return JsonResponse({
        'slots': slots,
        'date': date_str,
        'tenant_name': tenant.name
    })

@role_required(['owner'])
@tenant_owner_required  
def api_reservation_counts(request, tenant_slug):
    """月別予約件数取得API"""
    year = int(request.GET.get('year', datetime.now().year))
    month = int(request.GET.get('month', datetime.now().month))
    
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # 指定月の予約を取得
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    
    reservations = Reservation.objects.filter(
        tenant=tenant,
        date__range=[start_date, end_date]
    ).values('date').annotate(count=models.Count('id'))
    
    # 日付ごとの件数辞書を作成
    counts = {}
    for res in reservations:
        date_str = res['date'].strftime('%Y-%m-%d')
        counts[date_str] = res['count']
    
    return JsonResponse({
        'counts': counts,
        'year': year,
        'month': month
    })

@role_required(['owner'])
@tenant_owner_required
def api_reservation_detail(request, tenant_slug, reservation_id):
    """予約詳細取得API"""
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    reservation = get_object_or_404(Reservation, id=reservation_id, tenant=tenant)
    
    return JsonResponse({
        'id': reservation.id,
        'customer_name': reservation.customer_name,
        'customer_email': reservation.customer_email,
        'customer_phone': reservation.customer_phone,
        'date': reservation.date.strftime('%Y-%m-%d'),
        'time_slot': reservation.time_slot.strftime('%H:%M'),
        'menu_name': reservation.menu.name if reservation.menu else '未設定',
        'menu_price': reservation.menu.price if reservation.menu else 0,
        'created_at': reservation.created_at.strftime('%Y-%m-%d %H:%M')
    })

@role_required(['owner'])
@tenant_owner_required
def api_delete_reservation(request, tenant_slug, reservation_id):
    """予約削除API"""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE メソッドが必要です'}, status=405)
    
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    reservation = get_object_or_404(Reservation, id=reservation_id, tenant=tenant)
    
    # 予約を削除
    customer_name = reservation.customer_name
    date_time = f"{reservation.date} {reservation.time_slot}"
    reservation.delete()
    
    return JsonResponse({
        'success': True,
        'message': f'{customer_name}様の予約（{date_time}）を削除しました'
    })

@role_required(['owner'])
@tenant_owner_required
def api_create_reservation(request, tenant_slug):
    """オーナー代理予約作成API"""
    import json
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST メソッドが必要です'}, status=405)
    
    try:
        data = json.loads(request.body)
        tenant = get_object_or_404(Tenant, slug=tenant_slug)
        
        # バリデーション
        required_fields = ['date', 'time_slot', 'customer_name', 'customer_phone']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'error': f'{field} は必須です'}, status=400)
        
        # 日付・時間の変換
        reservation_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        reservation_time = datetime.strptime(data['time_slot'], '%H:%M').time()
        
        # 重複チェック
        existing = Reservation.objects.filter(
            tenant=tenant,
            date=reservation_date,
            time_slot=reservation_time
        ).exists()
        
        if existing:
            return JsonResponse({'error': 'この時間は既に予約済みです'}, status=400)
        
        # メニュー取得（オプション）
        menu = None
        if data.get('menu_id'):
            menu = Menu.objects.filter(id=data['menu_id'], tenant=tenant).first()
        
        # 予約作成
        reservation = Reservation.objects.create(
            tenant=tenant,
            menu=menu,
            customer_name=data['customer_name'][:100],
            customer_email=data.get('customer_email', ''),
            customer_phone=data['customer_phone'][:20],
            date=reservation_date,
            time_slot=reservation_time
        )
        
        # メール送信処理（no_emailフラグでコントロール）
        send_email = data.get('no_email', 'false').lower() != 'true'
        is_block = data.get('is_block', 'false').lower() == 'true'
        
        # デバッグログ
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Reservation created - Block: {is_block}, Send Email: {send_email}, Customer: {data.get('customer_name', 'N/A')}")
        
        if send_email and not is_block:
            try:
                # SMS送信処理（views.pyから正しくインポート）
                from .views import send_sms
                
                # 顧客へのSMS送信
                if reservation.customer_phone:
                    customer_message = f"{tenant.name}のご予約が完了しました。\n日時: {reservation_date} {reservation_time.strftime('%H:%M')}\nお名前: {reservation.customer_name}"
                    send_sms(reservation.customer_phone, customer_message)
                
                # オーナーへのSMS送信
                if tenant.owner.phone:
                    owner_message = f"新しい予約が入りました。\n日時: {reservation_date} {reservation_time.strftime('%H:%M')}\n顧客: {reservation.customer_name}"
                    send_sms(tenant.owner.phone, owner_message)
                    
            except Exception as e:
                # SMS送信失敗時のログ記録（予約作成は成功）
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"SMS sending failed for reservation {reservation.id}: {str(e)}")
        
        # レスポンスメッセージを調整
        if is_block:
            message = f'{reservation_date} {reservation_time.strftime("%H:%M")} をブロックしました'
        else:
            message = f'{data["customer_name"]}様の予約を作成しました'
        
        return JsonResponse({
            'success': True,
            'message': message,
            'reservation_id': reservation.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSONデータが不正です'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': '予約作成に失敗しました'}, status=500)