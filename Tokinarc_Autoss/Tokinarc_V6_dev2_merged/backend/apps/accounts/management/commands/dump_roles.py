"""
Tokinarc V6.C-fix — apps/accounts/management/commands/dump_roles.py

Sinh bảng phân quyền cho frontend (TypeScript) và chatbot (Python fallback)
TỪ NGUỒN CHÍNH `apps/accounts/roles.py`. Mục đích: loại bỏ việc chép tay bảng
quyền ở nhiều nơi (rủi ro lệch đã ghi trong EXTENDING.md §4).

Cách dùng:
    # In ra stdout
    python manage.py dump_roles --format=ts
    python manage.py dump_roles --format=py
    python manage.py dump_roles --format=json

    # Ghi thẳng vào file đích (đồng bộ frontend + chatbot)
    python manage.py dump_roles --format=ts --out ../frontend/src/lib/auth/roles.ts
    python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py

    # CI: kiểm tra file đã sinh có khớp nguồn không (exit !=0 nếu lệch)
    python manage.py dump_roles --format=ts --out ../frontend/src/lib/auth/roles.ts --check

Khi tách nhóm quyền mới (vd PURCHASING_ROLES) → CHỈ sửa roles.py rồi chạy lại
lệnh này. Không bao giờ sửa tay file sinh ra (header có cảnh báo).
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import roles as R

GEN_HEADER = "AUTO-GENERATED từ apps/accounts/roles.py — ĐỪNG SỬA TAY. Chạy: python manage.py dump_roles"


def _collect() -> dict:
    """Gom toàn bộ dữ liệu quyền từ roles.py thành dict thuần (sorted, ổn định)."""
    def sset(s):
        return sorted(s)

    return {
        "roles": sset(R.ALL_ROLES),
        "role_hierarchy": dict(sorted(R.ROLE_HIERARCHY.items(), key=lambda kv: kv[1])),
        "manager_roles": sset(R.MANAGER_ROLES),
        "read_tools": sset(R.READ_TOOLS),
        "write_tool_requirements": {k: sset(v) for k, v in sorted(R.WRITE_TOOL_REQUIREMENTS.items())},
        "read_tool_requirements": {k: sset(v) for k, v in sorted(R.READ_TOOL_REQUIREMENTS.items())},
    }


def _as_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _as_ts(data: dict) -> str:
    def arr(xs):
        return "[" + ", ".join(f"'{x}'" for x in xs) + "]"

    def rec(d):
        lines = []
        for k, v in d.items():
            lines.append(f"  '{k}': {arr(v)},")
        return "{\n" + "\n".join(lines) + "\n}"

    hier = "{\n" + "\n".join(f"  '{k}': {v}," for k, v in data["role_hierarchy"].items()) + "\n}"
    return (
        f"// {GEN_HEADER}\n"
        f"export const ROLES = {arr(data['roles'])} as const;\n"
        f"export type Role = typeof ROLES[number];\n\n"
        f"export const ROLE_HIERARCHY: Record<string, number> = {hier};\n\n"
        f"export const MANAGER_ROLES = {arr(data['manager_roles'])};\n\n"
        f"export const READ_TOOLS = {arr(data['read_tools'])};\n\n"
        f"export const WRITE_TOOL_REQUIREMENTS: Record<string, string[]> = {rec(data['write_tool_requirements'])};\n\n"
        f"export const READ_TOOL_REQUIREMENTS: Record<string, string[]> = {rec(data['read_tool_requirements'])};\n\n"
        f"export function canReadTool(role: string, tool: string): boolean {{\n"
        f"  if (!READ_TOOLS.includes(tool)) return false;\n"
        f"  const customerOk = ['search_parts', 'get_part', 'get_torch'];\n"
        f"  if (role === 'customer') return customerOk.includes(tool);\n"
        f"  const req = READ_TOOL_REQUIREMENTS[tool];\n"
        f"  return req ? req.includes(role) : true;\n"
        f"}}\n"
    )


def _as_py(data: dict) -> str:
    def fset(xs):
        return "frozenset({" + ", ".join(f"'{x}'" for x in xs) + "})"

    def reqdict(d):
        lines = []
        for k, v in d.items():
            lines.append(f"    '{k}': {fset(v)},")
        return "{\n" + "\n".join(lines) + "\n}"

    hier = "{\n" + "\n".join(f"    '{k}': {v}," for k, v in data["role_hierarchy"].items()) + "\n}"
    return (
        f'"""{GEN_HEADER}"""\n'
        f"from __future__ import annotations\n\n"
        f"ALL_ROLES = {fset(data['roles'])}\n"
        f"ROLE_HIERARCHY = {hier}\n"
        f"MANAGER_ROLES = {fset(data['manager_roles'])}\n"
        f"READ_TOOLS = {fset(data['read_tools'])}\n"
        f"WRITE_TOOL_REQUIREMENTS = {reqdict(data['write_tool_requirements'])}\n"
        f"READ_TOOL_REQUIREMENTS = {reqdict(data['read_tool_requirements'])}\n"
    )


RENDERERS = {"ts": _as_ts, "py": _as_py, "json": _as_json}


class Command(BaseCommand):
    help = "Sinh bảng phân quyền cho frontend/chatbot từ nguồn chính roles.py."

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=list(RENDERERS), default="json")
        parser.add_argument("--out", default=None, help="Đường dẫn file đích (mặc định: stdout).")
        parser.add_argument(
            "--check", action="store_true",
            help="Chỉ kiểm tra file --out có khớp nguồn không. Lệch → exit 1 (dùng cho CI).",
        )

    def handle(self, *args, **opts):
        fmt = opts["format"]
        out = opts["out"]
        check = opts["check"]

        content = RENDERERS[fmt](_collect())

        if check:
            if not out:
                raise CommandError("--check cần --out để so sánh.")
            try:
                with open(out, encoding="utf-8") as fh:
                    current = fh.read()
            except FileNotFoundError:
                raise CommandError(f"File chưa tồn tại: {out}. Chạy lệnh không có --check để sinh.")
            if current != content:
                self.stderr.write(self.style.ERROR(
                    f"LỆCH: {out} không khớp roles.py. Chạy: "
                    f"python manage.py dump_roles --format={fmt} --out {out}"
                ))
                sys.exit(1)
            self.stdout.write(self.style.SUCCESS(f"OK: {out} khớp nguồn."))
            return

        if out:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.stdout.write(self.style.SUCCESS(f"Đã ghi {fmt} → {out}"))
        else:
            self.stdout.write(content)
