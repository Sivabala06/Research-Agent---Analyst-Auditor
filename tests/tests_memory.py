import sys
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory import MemoryStore


def test_save_and_retrieve_similar_question(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.save_facts(["Infosys"], [("Salil Parekh is CEO", "https://real.com")], "Who is the CEO of Infosys?")
    facts = store.get_facts_for_entities(["Infosys"], "Who is Infosys's current CEO?")
    assert len(facts) == 1


def test_same_entity_different_intent_does_not_reuse_cache(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.save_facts(["Infosys"], [("Salil Parekh is CEO", "https://real.com")], "Who is the CEO of Infosys?")
    facts = store.get_facts_for_entities(["Infosys"], "Who is the CFO of Infosys and where did they work before?")
    assert facts == []  # this is the exact Q1/Q8 collision — must now be blocked


def test_unknown_entity_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    assert store.get_facts_for_entities(["Nobody"], "anything") == []


def test_facts_convert_to_usable_evidence_bundle(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.save_facts(["X"], [("fact one", "https://a.com")], "what about X?")
    facts = store.get_facts_for_entities(["X"], "what about X?")
    bundle = store.facts_to_evidence_bundle(facts)
    assert bundle.pieces[0].text == "fact one"


def test_legacy_database_is_migrated_and_unscored_facts_are_skipped(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL,
            statement TEXT NOT NULL, url TEXT NOT NULL, created_at REAL NOT NULL)""")
        conn.execute(
            "INSERT INTO entity_facts (entity, statement, url, created_at) VALUES (?, ?, ?, ?)",
            ("Infosys", "Legacy fact", "https://real.com", 1.0),
        )

    store = MemoryStore(db_path)

    assert store.get_facts_for_entities(["Infosys"], "Who is the CEO of Infosys?") == []