from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Reservation
from .utils import send_reservation_confirmation_email, send_business_notification_email
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Reservation)
def send_reservation_emails(sender, instance, created, **kwargs):
    """
    予約が作成された時に自動でメール通知を送信
    """
    if created:  # 新規作成時のみ
        try:
            # 予約者への確認メール送信
            confirmation_sent = send_reservation_confirmation_email(instance)
            
            # 事業者への通知メール送信
            notification_sent = send_business_notification_email(instance)
            
            if confirmation_sent and notification_sent:
                logger.info(f"予約ID {instance.id}: 両方のメール送信が完了しました")
            elif confirmation_sent:
                logger.warning(f"予約ID {instance.id}: 予約者メールのみ送信完了、事業者メール送信失敗")
            elif notification_sent:
                logger.warning(f"予約ID {instance.id}: 事業者メールのみ送信完了、予約者メール送信失敗")
            else:
                logger.error(f"予約ID {instance.id}: 両方のメール送信が失敗しました")
                
        except Exception as e:
            logger.error(f"予約ID {instance.id}: メール送信処理でエラーが発生しました: {e}")
