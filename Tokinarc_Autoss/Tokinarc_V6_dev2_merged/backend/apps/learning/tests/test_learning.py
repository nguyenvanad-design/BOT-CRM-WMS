"""
Tokinarc V6.C — apps/learning/tests/test_learning.py
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.learning.models import GoldenExample, QueryLog


@pytest.mark.django_db
def test_promotion_gate_promotes_qualifying():
    # đạt ngưỡng
    QueryLog.objects.create(session_id='s1', role='customer', query_text='béc N350A?',
                            response_text='...', confidence=0.91, critic_score=5,
                            planner_tools=['search_parts'])
    # không đạt (score thấp)
    QueryLog.objects.create(session_id='s2', role='customer', query_text='x',
                            response_text='y', confidence=0.95, critic_score=3)
    # không đạt (confidence thấp)
    QueryLog.objects.create(session_id='s3', role='customer', query_text='z',
                            response_text='w', confidence=0.5, critic_score=5)
    call_command('promote_golden')
    assert GoldenExample.objects.count() == 1
    assert GoldenExample.objects.first().query_text == 'béc N350A?'


@pytest.mark.django_db
def test_promotion_idempotent():
    QueryLog.objects.create(session_id='s1', role='customer', query_text='q',
                            response_text='a', confidence=0.9, critic_score=4)
    call_command('promote_golden')
    call_command('promote_golden')   # chạy lại không nhân đôi
    assert GoldenExample.objects.count() == 1
