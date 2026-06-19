"""
Tokinarc V6.C — apps/learning/management/commands/promote_golden.py

Promotion gate (B.5 §2.3): QueryLog đạt critic_score>=4 AND confidence>=0.85
→ tạo GoldenExample. Idempotent (đánh dấu promoted). Cron mỗi giờ sau critic.
"""
from django.core.management.base import BaseCommand
from apps.learning.models import GoldenExample, QueryLog

SCORE_MIN = 4
CONF_MIN = 0.85


class Command(BaseCommand):
    help = "Promote query log đạt ngưỡng lên Golden Store."

    def handle(self, **kw):
        cands = QueryLog.objects.filter(promoted=False, critic_score__gte=SCORE_MIN,
                                        confidence__gte=CONF_MIN)
        n = 0
        for lg in cands:
            GoldenExample.objects.create(
                source_log=lg, query_text=lg.query_text, ideal_tools=lg.planner_tools,
                ideal_answer=lg.response_text, score=lg.critic_score, confidence=lg.confidence)
            lg.promoted = True
            lg.save(update_fields=['promoted'])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"✅ Promoted {n} example."))
