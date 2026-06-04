"""
utils/chroma_utils.py
---------------------
Inspection utilities for the SQLite history DB and ChromaDB store.
"""

from pathlib import Path


def inspect_db(result_dir: Path) -> None:
    """Print row counts and recent records from SQLite and ChromaDB."""
    db_path     = result_dir / "history.db"
    chroma_path = result_dir / "chroma"

    sep = "-" * 56

    # ── SQLite ────────────────────────────────────────────────
    print("\n" + sep)
    print("  SQLite  ->", db_path)
    print(sep)
    if not db_path.exists():
        print("  [NOT FOUND] No history.db in", result_dir)
    else:
        import sqlite3
        conn = sqlite3.connect(str(db_path))

        for tbl in ("historical_llm_response", "recipient_network", "sender_weekly_volume"):
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:<35} {n:>5} row(s)")

        print()
        print("  Recent findings (last 10):")
        rows = conn.execute(
            "SELECT id, sender, subject, is_compliant, priority_band, created_at "
            "FROM historical_llm_response ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        if not rows:
            print("    (empty)")
        else:
            for r in rows:
                compliant = "OK " if not r[3] else "NON"
                print(f"    [{compliant}] {r[5]}  {r[1] or '(no sender)':30}  {r[2][:40] or '(no subject)'}")
        conn.close()

    # ── ChromaDB ──────────────────────────────────────────────
    print()
    print(sep)
    print("  ChromaDB  ->", chroma_path)
    print(sep)
    if not chroma_path.exists():
        print("  [NOT FOUND] No chroma/ folder in", result_dir)
    else:
        try:
            import chromadb
            col   = chromadb.PersistentClient(path=str(chroma_path)).get_collection("email_compliance")
            count = col.count()
            print(f"  Collection 'email_compliance'  {count} document(s)")
            if count:
                sample = col.get(limit=5, include=["metadatas"])
                print()
                print("  Sample (up to 5):")
                for meta in sample["metadatas"]:
                    print(f"    sender={meta.get('sender','?'):30}  compliant={meta.get('is_compliant','?')}  band={meta.get('priority_band','?')}")
        except ImportError:
            print("  chromadb not installed. Run: pip install chromadb")
        except Exception as exc:
            print("  ChromaDB error:", exc)

    print(sep + "\n")
