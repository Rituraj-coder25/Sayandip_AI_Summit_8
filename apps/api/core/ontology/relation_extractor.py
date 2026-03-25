from collections import Counter


class RelationExtractor:
    def extract(self, text: str, entities: list[dict]) -> list[dict]:
        names = [entity.get("text") for entity in entities if entity.get("text")]
        names = list(dict.fromkeys(names))[:8]
        if len(names) < 2:
            return []

        lowered = (text or "").lower()
        predicate = "related_to"
        if "near" in lowered:
            predicate = "near"
        elif "attacked" in lowered or "attack" in lowered:
            predicate = "attacked"
        elif "met" in lowered or "meeting" in lowered:
            predicate = "engaged"
        elif "trade" in lowered:
            predicate = "trades_with"

        relationships = []
        for left, right in zip(names, names[1:]):
            relationships.append(
                {
                    "subject": left,
                    "predicate": predicate,
                    "object": right,
                    "strength_score": 0.5,
                }
            )
        return relationships
