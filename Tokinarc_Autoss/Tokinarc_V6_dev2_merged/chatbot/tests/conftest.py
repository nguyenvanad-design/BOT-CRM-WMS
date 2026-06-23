"""
tests/conftest.py
==================
Session-scoped fixture init AssemblyKB + DataStore + CER + wire vào tool_wrappers.
Mirror logic từ main.py lifespan startup, nhưng bỏ những thứ không cần cho unit test
(Gemini, VectorIndex, BM25, PQA, GraphTraversal, QueryLogger).
"""
import sys
from pathlib import Path

# Add project root to sys.path so "core" module can be imported
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(scope="session", autouse=True)
def _init_singletons():
    """Init DataStore, CER, AssemblyKB và wire vào tool_wrappers — chạy 1 lần / session."""
    from core.data_store import (
        _resolve_data_path,
        _resolve_assembly_path,
        get_data_store,
    )
    from core.tokinarc_cer import get_cer
    from core.assembly_kb import AssemblyKB
    from core.tool_wrappers import (
        set_data_store,
        set_cer,
        set_assembly_kb,
    )

    data_file = _resolve_data_path()
    assembly_file = _resolve_assembly_path()

    ds = get_data_store(data_file, assembly_file)
    cer = get_cer(ds=ds)
    kb = AssemblyKB.from_file(assembly_file)

    set_data_store(ds)
    set_cer(cer)
    set_assembly_kb(kb)

    # GraphTraversal optional — không cần cho get_replacement_steps
    try:
        from core.graph_traversal import get_graph_traversal
        from core.tool_wrappers import set_graph_traversal
        set_graph_traversal(get_graph_traversal(cer))
    except Exception:
        pass

    print(f"\n[conftest] Initialized: ds={data_file}, kb={assembly_file}")
    yield
    # No teardown — singletons survive session

