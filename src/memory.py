"""
memory.py — SQLite entity memory with SEMANTIC RELEVANCE GATING.

BUG FOUND AND FIXED: the original version keyed cache purely by
entity name ("Infosys", "Indian") with the question's actual INTENT
ignored. Result: "Who is the CEO of Infosys?" and "Who is the CFO,
and where did they work before?" both matched on "Infosys" alone,
so the second question got served the first's cached CEO fact,
skipped search entirely, and returned a confidently wrong answer.
Same collision hit "Indian" between two unrelated questions.

FIX: fastembed (approved but previously unused) computes similarity
between the new question and the ORIGINAL question each cached fact
came from. A fact is reused only if the entity matches AND question
similarity clears SIMILARITY_THRESHOLD. TRADE-OFF (stated honestly):
this is more conservative than the letter of "answer faster about an
entity already researched" — we chose correctness over aggressive
reuse. A near-duplicate question gets a fast, correct cache hit; a
same-entity-different-intent question now correctly forces a fresh
search instead of reusing an unrelated cached fact.
"""
from __future__ import annotations
import sqlite3, time, json
from pathlib import Path
from pydantic import BaseModel
from fastembed import TextEmbedding
import numpy as np

from evidence import EvidenceBundle, EvidencePiece

DB_PATH = "research_memory.db"
SIMILARITY_THRESHOLD = 0.90

_embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")  # ~130MB, downloads once, CPU-friendly


def _embed(text: str) -> list[float]:
    return [float(value) for value in next(_embedder.embed([text]))]


def _cosine(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


class CachedFact(BaseModel):
    entity: str
    statement: str
    url: str
    source_question: str
    created_at: float


class MemoryStore:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = str(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL,
                statement TEXT NOT NULL, url TEXT NOT NULL,
                source_question TEXT NOT NULL, embedding TEXT NOT NULL,
                created_at REAL NOT NULL)""")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(entity_facts)")}
            if "source_question" not in columns:
                conn.execute(
                    "ALTER TABLE entity_facts ADD COLUMN source_question TEXT NOT NULL DEFAULT ''"
                )
            if "embedding" not in columns:
                conn.execute(
                    "ALTER TABLE entity_facts ADD COLUMN embedding TEXT NOT NULL DEFAULT '[]'"
                )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity ON entity_facts(entity)")

    def save_facts(self, entities: list[str], facts: list[tuple[str, str]], source_question: str) -> None:
        if not entities or not facts:
            return
        now = time.time()
        embedding = json.dumps(_embed(source_question))
        with sqlite3.connect(self.db_path) as conn:
            for entity in entities:
                for statement, url in facts:
                    conn.execute(
                        "INSERT INTO entity_facts (entity, statement, url, source_question, embedding, created_at) VALUES (?,?,?,?,?,?)",
                        (entity, statement, url, source_question, embedding, now))

    def get_facts_for_entities(self, entities: list[str], current_question: str) -> list[CachedFact]:
        if not entities:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            ph = ",".join("?" for _ in entities)
            rows = conn.execute(f"SELECT * FROM entity_facts WHERE entity IN ({ph})", entities).fetchall()
        if not rows:
            return []

        query_vec = _embed(current_question)
        relevant = []
        for r in rows:
            stored_vec = json.loads(r["embedding"])
            if len(stored_vec) != len(query_vec):
                continue
            score = _cosine(query_vec, stored_vec)
            if score >= SIMILARITY_THRESHOLD:
                relevant.append(CachedFact(entity=r["entity"], statement=r["statement"], url=r["url"],
                                            source_question=r["source_question"], created_at=r["created_at"]))
        return relevant

    def facts_to_evidence_bundle(self, facts: list[CachedFact]) -> EvidenceBundle:
        pieces = [EvidencePiece(sub_question="(from memory)", url=f.url,
                  title=f"Cached fact about {f.entity}", text=f.statement,
                  word_count=len(f.statement.split())) for f in facts]
        return EvidenceBundle(pieces=pieces)