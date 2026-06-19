"""
Tokinarc V6.C — apps/learning/management/commands/run_critic_batch.py

Critic batch (B.5 §2.2): chấm QueryLog chưa có critic_score bằng Gemini Flash.
Hàm score_one() tách riêng để test mock. Cron mỗi giờ.
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.learning.models import QueryLog

RUBRIC = ("Chấm 1-5 câu trả lời trợ lý hàn Tokinarc. 5=chính xác đúng tool không bịa, "
          "1=sai/bịa/lạc đề. Trả JSON {\"score\":int,\"note\":str}.")


def score_one(query_text: str, response_text: str) -> dict:
    """Gọi Gemini Flash. Tách hàm để test mock; ở đây fallback no-op."""
    try:
        from chatbot.llm import flash_json  # production helper
        return flash_json(RUBRIC, f"Q:{query_text}\nA:{response_text}")
    except Exception:
        return {}     # không chấm được → để None, lần sau thử lại


class Command(BaseCommand):
    help = "Chấm điểm QueryLog gần đây bằng Critic (Flash)."

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=1)
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, hours, limit, **kw):
        since = timezone.now() - timedelta(hours=hours)
        logs = QueryLog.objects.filter(critic_score__isnull=True, blocked=False,
                                       ts__gte=since)[:limit]
        n = 0
        for lg in logs:
            res = score_one(lg.query_text, lg.response_text)
            if res.get('score'):
                lg.critic_score = res['score']
                lg.critic_note = res.get('note', '')
                lg.save(update_fields=['critic_score', 'critic_note'])
                n += 1
        self.stdout.write(self.style.SUCCESS(f"✅ Critic scored {n} log."))
