"""
Nạp kiến thức LẮP ĐẶT / SỬA CHỮA từ chatbot (procedural_qa_kb.jsonl) vào DB nội bộ
để nhân sự (kỹ sư dịch vụ, kho) tra cứu.

    python manage.py seed_procedures
    python manage.py seed_procedures --file <đường_dẫn.jsonl>
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.catalog.models import ProcedureQA

# merged_root/chatbot/data/  (parents[5] = merged_root)
_DATA = Path(__file__).resolve().parents[5] / 'chatbot' / 'data'
_DEFAULT = _DATA / 'procedural_qa_kb.jsonl'
_ASM = _DATA / 'assembly_procedures_v1_3.json'


def _tables_to_qa() -> list:
    """Chuyển bảng torque/chiều dài (assembly_procedures.json) thành Q&A tra cứu."""
    from apps.catalog.models import ProcedureQA
    if not _ASM.exists():
        return []
    import json as _json
    d = _json.loads(_ASM.read_text(encoding='utf-8'))
    out = []

    def add(intent, q, a, src=''):
        out.append(ProcedureQA(intent=intent, question=q[:400], answer=a, source=src[:200]))

    for t in d.get('torque_specs', []):
        comp = t.get('component', '?')
        add('LOOKUP', f"Torque (lực vặn) cho {comp} bao nhiêu?",
            f"{comp}: {t.get('value_display') or str(t.get('value_nm',''))+' N·m'}. "
            f"Dụng cụ: {t.get('tool_recommended','—')}. Áp dụng: {t.get('applies_to','—')}",
            t.get('source', 'assembly_procedures'))
    for t in d.get('inner_tube_length_table', []):
        models_ = ', '.join(t.get('torch_models', []))
        add('LOOKUP', f"Chiều dài inner tube (ống trong) cho {models_}?",
            f"Mã {t.get('part_id','')} — súng {models_}: inner tube dài {t.get('inner_tube_length_mm')}mm.",
            t.get('source', 'assembly_procedures'))
    for t in d.get('liner_length_table', []):
        models_ = ', '.join(t.get('torch_models', []))
        add('LOOKUP', f"Chiều dài liner cho {models_}?",
            f"Mã {t.get('part_id','')} — súng {models_}: liner dài {t.get('liner_length_mm')}mm"
            + (f", dây {t.get('wire_size_mm')}mm" if t.get('wire_size_mm') else '') + '.',
            t.get('source', 'assembly_procedures'))
    for t in d.get('liner_protrusion_table', []):
        add('LOOKUP', f"Độ nhô liner (protrusion) cho súng {t.get('torch_model','')}?",
            f"Súng {t.get('torch_model','')}: liner nhô ra L = {t.get('protrusion_L_mm')}mm"
            + (f" ({t.get('note')})" if t.get('note') else '') + '.',
            t.get('source', 'assembly_procedures'))
    return out


class Command(BaseCommand):
    help = "Nạp Q&A lắp đặt/sửa chữa từ chatbot procedural_qa_kb.jsonl."

    def add_arguments(self, parser):
        parser.add_argument('--file', default=str(_DEFAULT))

    def handle(self, file, **kw):
        path = Path(file)
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"Không thấy file: {path}"))
            return
        rows = []
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = (d.get('question') or '').strip()
            a = (d.get('answer') or '').strip()
            if not q or not a:
                continue
            rows.append(ProcedureQA(
                intent=(d.get('intent') or 'LOOKUP').strip().upper()[:20],
                question=q[:400], answer=a, source=(d.get('source') or '')[:200],
            ))
        rows += _tables_to_qa()   # + bảng torque/chiều dài
        # Nạp lại sạch (idempotent).
        ProcedureQA.objects.all().delete()
        ProcedureQA.objects.bulk_create(rows, batch_size=200)
        from collections import Counter
        c = Counter(r.intent for r in rows)
        self.stdout.write(self.style.SUCCESS(
            f"✅ Nạp {len(rows)} Q&A lắp đặt/sửa chữa (+bảng kỹ thuật): "
            + ', '.join(f'{k}={v}' for k, v in c.most_common())))
