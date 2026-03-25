"""
Neo4j graph engine.
Every signal co-mention increments relationship strength to build a living graph.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("goe.graph")


class OntologyGraphEngine:
    def __init__(self, driver):
        self.driver = driver

    async def upsert_from_signal(self, entities: list[dict], relations: list[dict], signal: dict):
        if not entities:
            return

        try:
            async with self.driver.session() as session:
                now = datetime.now(timezone.utc).isoformat()
                for entity in entities:
                    label = self._map_label(entity.get("label", "ORG"))
                    await session.run(
                        f"""
                        MERGE (n:{label} {{name: $name}})
                        ON CREATE SET n.created_at = $now, n.mention_count = 1
                        ON MATCH  SET n.mention_count = coalesce(n.mention_count, 0) + 1,
                                      n.last_seen = $now
                        """,
                        name=entity.get("text"),
                        now=now,
                    )

                for relation in relations:
                    subject = relation.get("subject", "")
                    predicate = relation.get("predicate", "RELATED_TO").upper().replace(" ", "_")
                    obj = relation.get("object", "")
                    confidence = float(relation.get("confidence", 0.5))
                    if not subject or not obj or subject == obj:
                        continue
                    await session.run(
                        """
                        MERGE (a {name: $subject})
                        MERGE (b {name: $object})
                        MERGE (a)-[r:RELATED_TO]->(b)
                        ON CREATE SET r.predicate = $predicate,
                                      r.strength_score = $confidence,
                                      r.mention_count = 1,
                                      r.first_seen = $now,
                                      r.last_seen = $now
                        ON MATCH SET  r.predicate = coalesce(r.predicate, $predicate),
                                      r.strength_score = coalesce(r.strength_score, 0) + ($confidence * 0.1),
                                      r.mention_count = coalesce(r.mention_count, 0) + 1,
                                      r.last_seen = $now
                        """,
                        subject=subject,
                        object=obj,
                        predicate=predicate,
                        confidence=confidence,
                        now=now,
                    )
        except Exception as exc:
            logger.error("Graph upsert failed: %s", exc)

    async def get_entity_neighborhood(self, entity_name: str, depth: int = 2) -> dict:
        max_depth = max(1, min(depth, 4))
        query = f"""
            MATCH path = (n {{name: $name}})-[*1..{max_depth}]-(m)
            WITH relationships(path) as rels, nodes(path) as ns
            UNWIND range(0, size(rels) - 1) as idx
            WITH ns[idx] as src, ns[idx + 1] as tgt, rels[idx] as rel
            RETURN
                src.name as src_name,
                labels(src)[0] as src_type,
                tgt.name as tgt_name,
                labels(tgt)[0] as tgt_type,
                type(rel) as rel_type,
                rel.strength_score as strength,
                rel.tension_level as tension,
                rel.mention_count as mentions
            LIMIT 200
        """
        async with self.driver.session() as session:
            result = await session.run(query, name=entity_name)
            rows = [record.data() async for record in result]

        nodes, links = {}, []
        for row in rows:
            for name, node_type in [(row.get("src_name"), row.get("src_type")), (row.get("tgt_name"), row.get("tgt_type"))]:
                if name and name not in nodes:
                    nodes[name] = {
                        "id": name,
                        "label": name,
                        "type": node_type or "Entity",
                        "size": 22 if name == entity_name else 12,
                    }
            if row.get("src_name") and row.get("tgt_name"):
                links.append(
                    {
                        "source": row["src_name"],
                        "target": row["tgt_name"],
                        "type": row.get("rel_type") or "RELATED_TO",
                        "strength": float(row.get("strength") or 0.3),
                        "tension": row.get("tension"),
                        "mentions": int(row.get("mentions") or 1),
                    }
                )
        return {"nodes": list(nodes.values()), "links": links}

    async def find_all_paths(self, entity_a: str, entity_b: str, max_hops: int = 6) -> list[dict]:
        query = (
            "MATCH path = allShortestPaths((a {name: $a})-[*..%d]-(b {name: $b})) "
            "RETURN [node in nodes(path) | node.name] as nodes, "
            "[rel in relationships(path) | type(rel)] as rels, "
            "length(path) as hops ORDER BY hops LIMIT 5"
        ) % max_hops
        async with self.driver.session() as session:
            result = await session.run(query, a=entity_a, b=entity_b)
            return [record.data() async for record in result]

    @staticmethod
    def _map_label(spacy_label: str) -> str:
        return {
            "GPE": "Nation",
            "LOC": "Location",
            "ORG": "Organisation",
            "PERSON": "Person",
            "NORP": "Group",
            "EVENT": "Event",
            "FAC": "Facility",
            "PRODUCT": "Technology",
        }.get(spacy_label, "Entity")


GraphEngine = OntologyGraphEngine