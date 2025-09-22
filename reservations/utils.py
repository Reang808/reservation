from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
import logging

logger = logging.getLogger(__name__)

def send_reservation_confirmation_email(reservation):
    """予約者に予約確認メールを送信"""
    if not settings.ENABLE_RESERVATION_NOTIFICATIONS:
        logger.info("メール通知が無効になっています")
        return False
    
    if not reservation.customer_email:
        logger.warning(f"予約ID {reservation.id}: 顧客のメールアドレスが設定されていません")
        return False
    
    try:
        tenant = reservation.tenant
        
        # 変数の置換
        subject = tenant.customer_email_subject.format(
            店舗名=tenant.name,
            お客様名=reservation.customer_name,
            予約日時=f"{reservation.date} {reservation.time_slot}",
            電話番号=reservation.customer_phone,
            メールアドレス=reservation.customer_email
        )
        
        message = tenant.customer_email_message.format(
            店舗名=tenant.name,
            お客様名=reservation.customer_name,
            予約日時=f"{reservation.date} {reservation.time_slot}",
            電話番号=reservation.customer_phone,
            メールアドレス=reservation.customer_email
        )
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reservation.customer_email],
            fail_silently=False,
        )
        
        logger.info(f"予約確認メールを送信しました: {reservation.customer_email}")
        return True
        
    except Exception as e:
        logger.error(f"予約確認メール送信エラー: {e}")
        return False

def send_business_notification_email(reservation):
    """事業者に予約通知メールを送信"""
    if not settings.ENABLE_RESERVATION_NOTIFICATIONS:
        logger.info("メール通知が無効になっています")
        return False
    
    tenant = reservation.tenant
    # 通知先メールアドレスを決定（設定されていればそれを、なければオーナーのメールアドレス）
    notification_email = tenant.notification_email or tenant.owner.email
    
    if not notification_email:
        logger.warning(f"予約ID {reservation.id}: 事業者の通知先メールアドレスが設定されていません")
        return False
    
    try:
        # 変数の置換
        subject = tenant.owner_email_subject.format(
            店舗名=tenant.name,
            お客様名=reservation.customer_name,
            予約日時=f"{reservation.date} {reservation.time_slot}",
            電話番号=reservation.customer_phone,
            メールアドレス=reservation.customer_email or '-'
        )
        
        message = tenant.owner_email_message.format(
            店舗名=tenant.name,
            お客様名=reservation.customer_name,
            予約日時=f"{reservation.date} {reservation.time_slot}",
            電話番号=reservation.customer_phone,
            メールアドレス=reservation.customer_email or '-'
        )
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification_email],
            fail_silently=False,
        )
        
        logger.info(f"事業者通知メールを送信しました: {notification_email}")
        return True
        
    except Exception as e:
        logger.error(f"事業者通知メール送信エラー: {e}")
        return False
