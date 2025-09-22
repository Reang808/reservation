from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta, time, date
from .models import Menu, Reservation, Tenant
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .decorators import role_required, tenant_owner_required
from django.contrib import messages
from django.core.exceptions import ValidationError
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
        
        return redirect('owner_reserve_list_by_tenant', tenant_slug=tenant.slug)
    
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
        
        return redirect('owner_reserve_list_by_tenant', tenant_slug=tenant.slug)
    
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
        
        return redirect('owner_reserve_list_by_tenant', tenant_slug=tenant.slug)
    
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