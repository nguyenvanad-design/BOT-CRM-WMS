"""
Tokinarc V6.C — apps/learning/models.py

Vòng học offline (B.5 §2): sidecar ghi QueryLog → cron Critic chấm điểm →
Promotion gate → GoldenExample (few-shot bơm ngược Planner).
EventDeadLetter: bù retry cho LISTEN/NOTIFY (B.1 §5.4).
"""
from __future__ import annotations

from django.db import models


class QueryLog(models.Model):
    id            = models.BigAutoField(primary_key=True)
    ts            = models.DateTimeField(auto_now_add=True, db_index=True)
    session_id    = models.CharField(max_length=64, db_index=True)
    role          = models.CharField(max_length=20)
    query_text    = models.TextField()
    planner_tools = models.JSONField(default=list)
    response_text = models.TextField(blank=True)
    confidence    = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    conf_tier     = models.CharField(max_length=10, blank=True)
    latency_ms    = models.IntegerField(null=True, blank=True)
    blocked       = models.BooleanField(default=False)        # guardrail chặn
    critic_score  = models.IntegerField(null=True, blank=True, db_index=True)  # 1..5
    critic_note   = models.TextField(blank=True)
    promoted      = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = 'learning_querylog'
        ordering = ['-ts']


class GoldenExample(models.Model):
    id           = models.BigAutoField(primary_key=True)
    source_log   = models.ForeignKey(QueryLog, null=True, blank=True, on_delete=models.SET_NULL)
    query_text   = models.TextField()
    ideal_tools  = models.JSONField(default=list)
    ideal_answer = models.TextField()
    tags         = models.JSONField(default=list)
    score        = models.IntegerField()
    confidence   = models.DecimalField(max_digits=4, decimal_places=3)
    active       = models.BooleanField(default=True, db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'learning_goldenexample'
        ordering = ['-created_at']


class EventDeadLetter(models.Model):
    id       = models.BigAutoField(primary_key=True)
    channel  = models.CharField(max_length=40, db_index=True)
    payload  = models.JSONField()
    error    = models.TextField()
    ts       = models.DateTimeField(auto_now_add=True)
    retries  = models.IntegerField(default=0)
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = 'learning_eventdeadletter'
        ordering = ['-ts']
